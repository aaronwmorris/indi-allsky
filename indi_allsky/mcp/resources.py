"""MCP Resources for INDI Allsky."""

import json
from typing import Any


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def register_resources(mcp_server: Any) -> None:
    """Register standard read-only resources with the MCPServer instance."""

    @mcp_server.resource("allsky://config/active")
    def get_active_config_resource() -> str:
        """Active system configuration JSON."""
        from ..config import IndiAllSkyConfig

        app = _get_flask_app()
        with app.app_context():
            config_obj = IndiAllSkyConfig()
            return json.dumps(dict(config_obj.config), default=str, indent=2)

    @mcp_server.resource("allsky://camera/status")
    def get_camera_status_resource() -> str:
        """Primary camera device status and hardware parameters."""
        from ..flask.models import IndiAllSkyDbCameraTable

        app = _get_flask_app()
        with app.app_context():
            camera = IndiAllSkyDbCameraTable.query.first()
            if not camera:
                return json.dumps({"status": "no_camera_configured"})
            return json.dumps(
                {
                    "id": camera.id,
                    "name": camera.name,
                    "driver": camera.driver,
                    "connected": camera.connectDate.isoformat() if camera.connectDate else None,
                    "width": camera.width,
                    "height": camera.height,
                    "pixelSize": camera.pixelSize,
                    "minExposure": camera.minExposure,
                    "maxExposure": camera.maxExposure,
                    "minGain": camera.minGain,
                    "maxGain": camera.maxGain,
                    "daytime_capture": camera.daytime_capture,
                    "capture_pause": camera.capture_pause,
                },
                indent=2,
            )

    @mcp_server.resource("allsky://images/latest")
    def get_latest_image_resource() -> str:
        """Metadata for the most recently captured image."""
        from ..flask.models import IndiAllSkyDbImageTable

        app = _get_flask_app()
        with app.app_context():
            image = (
                IndiAllSkyDbImageTable.query.order_by(IndiAllSkyDbImageTable.createDate.desc())
                .first()
            )
            if not image:
                return json.dumps({"status": "no_images_found"})
            return json.dumps(
                {
                    "id": image.id,
                    "filename": image.filename,
                    "createDate": image.createDate.isoformat() if image.createDate else None,
                    "exposure": image.exposure,
                    "gain": image.gain,
                    "binmode": image.binmode,
                    "night": image.night,
                    "adu": image.adu,
                    "sqm": image.sqm,
                    "stars": image.stars,
                    "detections": image.detections,
                },
                indent=2,
            )
