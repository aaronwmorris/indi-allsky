"""Dark frame library tools for INDI Allsky MCP server."""

from typing import Any, Dict, List
import logging

logger = logging.getLogger('indi_allsky.mcp.darks')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def audit_dark_library() -> Dict[str, Any]:
    """Audit the master dark frame library to identify calibration temperature and exposure gaps."""
    from ..flask.models import IndiAllSkyDbDarkFrameTable

    app = _get_flask_app()
    with app.app_context():
        darks = IndiAllSkyDbDarkFrameTable.query.filter(
            IndiAllSkyDbDarkFrameTable.active == True  # noqa: E712
        ).all()

        bins: List[Dict[str, Any]] = []
        for d in darks:
            bins.append(
                {
                    "dark_id": d.id,
                    "exposure": d.exposure,
                    "gain": d.gain,
                    "binmode": d.binmode,
                    "temp": d.temp,
                    "bitdepth": d.bitdepth,
                    "filename": d.filename,
                }
            )

        return {
            "status": "success",
            "total_active_darks": len(darks),
            "dark_bins": bins,
        }


def register_dark_tools(mcp_server: Any) -> None:
    """Register dark library tools with the MCPServer instance."""
    mcp_server.tool()(audit_dark_library)
