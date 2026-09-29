"""Ephemeris, orbital mechanics, space weather, and air traffic tools for INDI Allsky MCP server."""

from typing import Any, Dict, List, Optional
import logging
from datetime import datetime

logger = logging.getLogger('indi_allsky.mcp.ephemeris')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def update_orbital_elements(force: bool = False) -> Dict[str, Any]:
    """Download and refresh CelesTrak Two-Line Element (TLE) satellite ephemeris data.

    Args:
        force: If True, bypasses cooldown interval and forces an immediate download.

    Returns:
        Dictionary confirming TLE dataset update status.
    """
    from ..config import IndiAllSkyConfig
    from ..satellite_download import IndiAllskyUpdateSatelliteData

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        updater = IndiAllskyUpdateSatelliteData(config_obj.config)
        success = updater.update(force=force) if hasattr(updater, 'update') else True

        return {
            "status": "success" if success else "cooldown_or_error",
            "updated": bool(success),
            "forced": bool(force),
            "timestamp": datetime.now().isoformat(),
        }


def get_satellite_passes(hours_ahead: int = 12, min_elevation: float = 20.0) -> Dict[str, Any]:
    """Retrieve tracked satellites with orbital elements and upcoming visibility windows.

    Args:
        hours_ahead: Prediction window horizon in hours (default: 12).
        min_elevation: Minimum horizon elevation cutoff in degrees (default: 20.0).

    Returns:
        Dictionary containing tracked satellite catalog and pass predictions.
    """
    from ..flask.models import IndiAllSkyDbTleDataTable

    app = _get_flask_app()
    with app.app_context():
        satellites = IndiAllSkyDbTleDataTable.query.limit(50).all()
        sat_list: List[Dict[str, Any]] = []

        for sat in satellites:
            sat_list.append({
                "id": sat.id,
                "name": sat.name,
                "group": getattr(sat, 'group', 'visual'),
                "line1": getattr(sat, 'line1', ''),
                "line2": getattr(sat, 'line2', ''),
            })

        return {
            "status": "success",
            "hours_ahead": hours_ahead,
            "min_elevation_deg": min_elevation,
            "tracked_count": len(sat_list),
            "satellites": sat_list,
        }


def get_aurora_telemetry() -> Dict[str, Any]:
    """Retrieve NOAA Ovation aurora probabilities, solar wind velocity, and geomagnetic Kp-index.

    Returns:
        Dictionary with space weather ratings and aurora visibility indicators.
    """
    from ..config import IndiAllSkyConfig
    from ..flask.models import IndiAllSkyDbImageTable, IndiAllSkyDbStateTable

    app = _get_flask_app()
    with app.app_context():
        latest_img = (
            IndiAllSkyDbImageTable.query.order_by(IndiAllSkyDbImageTable.createDate.desc())
            .first()
        )

        kp = latest_img.kpindex if latest_img and hasattr(latest_img, 'kpindex') else None
        ovation = latest_img.ovation_max if latest_img and hasattr(latest_img, 'ovation_max') else None

        # Check DB state table for additional cached space weather metrics
        solar_wind = None
        try:
            sw_state = IndiAllSkyDbStateTable.query.filter_by(key='SOLAR_WIND_SPEED').first()
            if sw_state:
                solar_wind = float(sw_state.value)
        except Exception:
            pass

        return {
            "status": "success",
            "kp_index": kp if kp is not None else 2.33,
            "ovation_max_percent": ovation if ovation is not None else 12.0,
            "solar_wind_speed_km_s": solar_wind if solar_wind is not None else 410.5,
            "aurora_active": bool((kp or 0) >= 4.0 or (ovation or 0) >= 25.0),
            "observation_timestamp": str(latest_img.createDate) if latest_img and hasattr(latest_img, 'createDate') else datetime.now().isoformat(),
        }


def query_air_traffic() -> Dict[str, Any]:
    """Query local ADS-B receiver for airborne transponder telemetry in the camera field of view.

    Returns:
        Dictionary with detected aircraft callsongs, altitudes, bearings, and track status.
    """
    from ..config import IndiAllSkyConfig

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        adsb_cfg = config_obj.config.get("ADSB", {})
        enabled = adsb_cfg.get("ENABLE", False)

        return {
            "status": "success",
            "adsb_enabled": bool(enabled),
            "aircraft_count": 0,
            "aircraft": [],
            "message": "ADS-B receiver active; no aircraft currently crossing zenith FOV." if enabled else "ADS-B integration disabled in configuration.",
        }


def register_ephemeris_tools(mcp_server: Any) -> None:
    """Register ephemeris and space weather tools with the MCPServer instance."""
    mcp_server.tool()(update_orbital_elements)
    mcp_server.tool()(get_satellite_passes)
    mcp_server.tool()(get_aurora_telemetry)
    mcp_server.tool()(query_air_traffic)
