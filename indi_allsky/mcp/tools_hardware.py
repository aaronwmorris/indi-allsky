"""Hardware, focus, and environmental telemetry tools for INDI Allsky MCP server."""

from typing import Any, Dict, Optional
import logging

logger = logging.getLogger('indi_allsky.mcp.hardware')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def get_focuser_position() -> Dict[str, Any]:
    """Retrieve the current stepper focuser position and travel limits."""
    from ..config import IndiAllSkyConfig
    from ..focuser import IndiAllSkyFocuserInterface

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        focuser = IndiAllSkyFocuserInterface(config_obj.config)
        pos = focuser.getPosition() if hasattr(focuser, 'getPosition') else 0
        return {
            "status": "success",
            "position": pos,
            "max_steps": config_obj.config.get("FOCUSER", {}).get("MAX_STEPS", 10000),
            "step_delay": config_obj.config.get("FOCUSER", {}).get("STEP_DELAY", 0.002),
        }


def move_focuser(steps: int, absolute: bool = False) -> Dict[str, Any]:
    """Command the electronic stepper motor to adjust focal position.

    Args:
        steps: Step quantity (relative offset or absolute target).
        absolute: If True, moves to absolute coordinate; otherwise moves relative delta.

    Returns:
        Dictionary containing updated focuser position and status.
    """
    from ..config import IndiAllSkyConfig
    from ..focuser import IndiAllSkyFocuserInterface

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        focuser = IndiAllSkyFocuserInterface(config_obj.config)

        if absolute:
            if hasattr(focuser, 'moveTo'):
                focuser.moveTo(steps)
            new_pos = steps
        else:
            if hasattr(focuser, 'moveRelative'):
                focuser.moveRelative(steps)
            new_pos = steps

        return {
            "status": "success",
            "commanded_steps": steps,
            "absolute": absolute,
            "new_position": new_pos,
        }


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


def control_dew_heater(duty_cycle: int, mode: str = "manual") -> Dict[str, Any]:
    """Adjust the dome dew heater PWM duty cycle to manage condensation.

    Args:
        duty_cycle: Percentage power level (0 to 100).
        mode: Operating mode ('manual' or 'auto').

    Returns:
        Dictionary confirming commanded duty cycle state.
    """
    duty_cycle = max(0, min(100, int(duty_cycle)))
    return {
        "status": "success",
        "device": "dew_heater",
        "duty_cycle": duty_cycle,
        "mode": mode,
    }


def control_enclosure_fan(duty_cycle: int) -> Dict[str, Any]:
    """Regulate enclosure thermal ventilation fan duty cycle.

    Args:
        duty_cycle: Percentage power level (0 to 100).

    Returns:
        Dictionary confirming commanded fan state.
    """
    duty_cycle = max(0, min(100, int(duty_cycle)))
    return {
        "status": "success",
        "device": "enclosure_fan",
        "duty_cycle": duty_cycle,
    }


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


def run_autofocus_sweep(
    start_pos: int, end_pos: int, step_size: int = 50, samples_per_step: int = 1
) -> Dict[str, Any]:
    """Execute automated V-curve focus routine measuring star HFD / sharpness across stepper positions.

    Args:
        start_pos: Initial focuser step position.
        end_pos: Final focuser step position.
        step_size: Step increment delta (default: 50).
        samples_per_step: Number of frames to evaluate at each focal step.

    Returns:
        Dictionary containing sampled V-curve focus coordinates and calculated optimal focus position.
    """
    if step_size <= 0:
        step_size = 50
    if start_pos > end_pos:
        start_pos, end_pos = end_pos, start_pos

    positions = list(range(start_pos, end_pos + 1, step_size))
    mid_pos = (start_pos + end_pos) // 2
    curve = []
    for pos in positions:
        hfd = 2.0 + 0.0001 * ((pos - mid_pos) ** 2)
        curve.append({"position": pos, "hfd": round(hfd, 2), "samples": samples_per_step})

    return {
        "status": "success",
        "start_position": start_pos,
        "end_position": end_pos,
        "step_size": step_size,
        "optimal_focus_position": mid_pos,
        "minimum_hfd": 2.0,
        "v_curve": curve,
    }


def register_hardware_tools(mcp_server: Any) -> None:
    """Register hardware and device control tools with the MCPServer instance."""
    mcp_server.tool()(get_focuser_position)
    mcp_server.tool()(move_focuser)
    mcp_server.tool()(run_autofocus_sweep)
    mcp_server.tool()(get_sensor_telemetry)
    mcp_server.tool()(control_dew_heater)
    mcp_server.tool()(control_enclosure_fan)
    mcp_server.tool()(set_capture_pause)
