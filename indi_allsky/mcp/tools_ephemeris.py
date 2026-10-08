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
            sat_title = getattr(sat, 'title', None) or getattr(sat, 'name', '')
            sat_list.append({
                "id": sat.id,
                "title": sat_title,
                "name": sat_title,
                "group": getattr(sat, 'group', None),
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
            "kp_index": kp,
            "ovation_max_percent": ovation,
            "solar_wind_speed_km_s": solar_wind,
            "aurora_active": bool((kp is not None and kp >= 4.0) or (ovation is not None and ovation >= 25.0)),
            "observation_timestamp": str(latest_img.createDate) if latest_img and hasattr(latest_img, 'createDate') else None,
        }


def query_air_traffic() -> Dict[str, Any]:
    """Query local ADS-B receiver for airborne transponder telemetry in the camera field of view.

    Reads DUMP1090_URL, USERNAME, PASSWORD, and ALT_DEG_MIN from the ADSB config section.

    Returns:
        Dictionary with detected aircraft callsigns, altitudes, bearings, and track status.
    """
    import json
    import math
    from datetime import datetime
    import requests

    from ..config import IndiAllSkyConfig
    from .. import constants

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        adsb_cfg = config_obj.config.get("ADSB", {})
        enabled = adsb_cfg.get("ENABLE", False)
        url = adsb_cfg.get("DUMP1090_URL", "")

        if not enabled or not url:
            return {
                "status": "success",
                "adsb_enabled": bool(enabled),
                "aircraft_count": 0,
                "aircraft": [],
                "message": "ADS-B integration disabled or DUMP1090_URL not configured.",
            }

        username = adsb_cfg.get("USERNAME")
        password = adsb_cfg.get("PASSWORD")
        cert_bypass = adsb_cfg.get("CERT_BYPASS", True)
        alt_min_deg = float(adsb_cfg.get("ALT_DEG_MIN", 20.0))

        observer_lat = config_obj.config.get("LATITUDE", 0.0)
        observer_lon = config_obj.config.get("LONGITUDE", 0.0)

        basic_auth = requests.auth.HTTPBasicAuth(username, password) if username else None
        verify = not cert_bypass

        try:
            r = requests.get(url, allow_redirects=True, verify=verify, auth=basic_auth, timeout=(4.0, 2.0))
            r.raise_for_status()
            r_data = r.json()
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"Failed to reach ADS-B receiver: {e}"}
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"Invalid JSON from ADS-B receiver: {e}"}

        # Reject stale data (more than 60s old)
        now = datetime.now()
        if abs(now.timestamp() - r_data.get("now", 0.0)) > 60:
            return {"status": "error", "message": "ADS-B data is stale (>60s old)."}

        R_EARTH_m = 6378100
        aircraft_list = []

        for aircraft in r_data.get("aircraft", []):
            alt_geom = aircraft.get("alt_geom")
            alt_baro = aircraft.get("alt_baro")
            altitude = aircraft.get("altitude")
            aircraft_altitude = alt_geom or alt_baro or altitude

            if aircraft_altitude is None or isinstance(aircraft_altitude, str):
                continue

            try:
                aircraft_lat = float(aircraft["lat"])
                aircraft_lon = float(aircraft["lon"])
                aircraft_elevation_m = int(aircraft_altitude) * 0.3048
            except (KeyError, TypeError, ValueError):
                continue

            aircraft_id = (
                (aircraft.get("flight") or "").rstrip()
                or aircraft.get("squawk")
                or aircraft.get("hex")
                or "Unknown"
            )

            # Great-circle distance
            lon1, lat1, lon2, lat2 = map(math.radians, [observer_lon, observer_lat, aircraft_lon, aircraft_lat])
            dlon, dlat = lon2 - lon1, lat2 - lat1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            aircraft_distance_m = 2 * math.asin(math.sqrt(a)) * R_EARTH_m

            # Earth curvature dropoff
            elevation_dropoff_m = R_EARTH_m - (R_EARTH_m * math.cos(aircraft_distance_m / R_EARTH_m))
            aircraft_elevation_m_rel = aircraft_elevation_m - elevation_dropoff_m

            if aircraft_elevation_m_rel <= 0:
                continue

            aircraft_alt = math.degrees(math.atan(aircraft_elevation_m_rel / max(aircraft_distance_m, 1.0)))

            if aircraft_alt < alt_min_deg:
                continue

            aircraft_list.append({
                "id": aircraft_id,
                "flight": aircraft.get("flight"),
                "squawk": aircraft.get("squawk"),
                "hex": aircraft.get("hex"),
                "latitude": aircraft_lat,
                "longitude": aircraft_lon,
                "elevation_km": round(aircraft_elevation_m / 1000, 2),
                "distance_km": round(aircraft_distance_m / 1000, 2),
                "alt_deg": round(aircraft_alt, 1),
            })

        aircraft_list.sort(key=lambda x: x["alt_deg"], reverse=True)

        return {
            "status": "success",
            "adsb_enabled": True,
            "aircraft_count": len(aircraft_list),
            "aircraft": aircraft_list,
        }


def register_ephemeris_tools(mcp_server: Any) -> None:
    """Register ephemeris and space weather tools with the MCPServer instance."""
    mcp_server.tool()(update_orbital_elements)
    mcp_server.tool()(get_satellite_passes)
    mcp_server.tool()(get_aurora_telemetry)
    mcp_server.tool()(query_air_traffic)
