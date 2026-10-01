"""Hardware and environmental telemetry tools for INDI Allsky MCP server."""

from typing import Any, Dict
import logging

logger = logging.getLogger('indi_allsky.mcp.hardware')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def get_sensor_telemetry() -> Dict[str, Any]:
    """Read ambient environmental sensors, dome SQM, and enclosure diagnostics.

    Returns:
        Dictionary with ambient temp, humidity, dew point, infrared sky temp, and SQM rating.
    """
    from ..config import IndiAllSkyConfig
    from ..sensors_mapping import get_latest_sensors_payload
    from ..flask.models import IndiAllSkyDbImageTable

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()

        # Query latest image for ambient sensor tags
        latest_img = (
            IndiAllSkyDbImageTable.query.order_by(IndiAllSkyDbImageTable.createDate.desc())
            .first()
        )

        sensor_data: Dict[str, Any] = {
            "status": "success",
            "sqm": latest_img.sqm if latest_img else None,
            "sensor_temperature": latest_img.temp if latest_img else None,
            "last_image_date": str(latest_img.createDate) if latest_img and hasattr(latest_img, 'createDate') else None,
        }

        try:
            payload = get_latest_sensors_payload(config_obj.config)
            if payload:
                sensor_data["sensors"] = payload.get("sensors", {})
                sensor_data["last_update"] = payload.get("last_update")
                sensor_data["last_update_age_s"] = payload.get("last_update_age_s")
        except Exception as e:
            sensor_data["sensors_warning"] = str(e)

        return sensor_data


def set_capture_pause(pause: bool) -> Dict[str, Any]:
    """Pause or resume the main camera exposure loop via the asynchronous task queue.

    Args:
        pause: True to pause capture loop; False to resume.

    Returns:
        Dictionary confirming task queue submission.
    """
    from ..flask import db
    from ..flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueQueue, TaskQueueState

    app = _get_flask_app()
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                "action": "setpaused",
                "pause": bool(pause),
            },
        )
        db.session.add(task)
        db.session.commit()

        return {
            "status": "success",
            "task_id": task.id,
            "action": "setpaused",
            "pause": bool(pause),
        }


def register_hardware_tools(mcp_server: Any) -> None:
    """Register hardware and device control tools with the MCPServer instance."""
    mcp_server.tool()(get_sensor_telemetry)
    mcp_server.tool()(set_capture_pause)
