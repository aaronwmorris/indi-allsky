"""Operations, log stream, task queue, and media compounding tools for INDI Allsky MCP server."""

from typing import Any, Dict, List, Optional
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger('indi_allsky.mcp.ops')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def get_system_logs(
    log_type: str = "app", lines: int = 100, filter_str: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve recent log stream entries for diagnosing driver failures or capture errors.

    Args:
        log_type: 'app' (indi-allsky daemon), 'indiserver', or 'syslog'.
        lines: Number of log lines to retrieve (default: 100).
        filter_str: Optional substring to filter lines.

    Returns:
        Dictionary containing log lines and metadata.
    """
    log_file_map = {
        "app": Path("/var/log/indi-allsky/indi-allsky.log"),
        "indiserver": Path("/var/log/indi-allsky/indiserver.log"),
        "syslog": Path("/var/log/syslog"),
    }

    target_path = log_file_map.get(log_type, log_file_map["app"])
    lines_output = []

    if target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                if filter_str:
                    all_lines = [l for l in all_lines if filter_str in l]
                lines_output = all_lines[-lines:]
        except Exception as e:
            return {"status": "error", "message": f"Failed to read log file {target_path}: {e}"}
    else:
        # Fallback to journalctl if log file not directly accessible
        try:
            unit = "indi-allsky.service" if log_type == "app" else "indiserver.service"
            cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                raw_lines = proc.stdout.splitlines()
                if filter_str:
                    raw_lines = [l for l in raw_lines if filter_str in l]
                lines_output = raw_lines
        except Exception as e:
            lines_output = [f"No direct log file at {target_path} and journalctl failed: {e}"]

    return {
        "status": "success",
        "log_type": log_type,
        "line_count": len(lines_output),
        "lines": lines_output,
    }


def get_hardware_throttling() -> Dict[str, Any]:
    """Check host CPU temperatures, undervoltage, and frequency throttling state."""
    res: Dict[str, Any] = {
        "status": "success",
        "throttled": False,
        "raw_flags": "0x0",
    }

    # Attempt vcgencmd for Raspberry Pi platforms
    try:
        proc = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
        if proc.returncode == 0 and "throttled=" in proc.stdout:
            val_str = proc.stdout.strip().split("=")[1]
            res["raw_flags"] = val_str
            val = int(val_str, 16)
            res["throttled"] = val != 0
            res["undervoltage_detected"] = bool(val & 0x1)
            res["frequency_capped"] = bool(val & 0x2)
            res["currently_throttled"] = bool(val & 0x4)
            res["temperature_limit_active"] = bool(val & 0x8)
    except Exception:
        pass

    return res


def inspect_task_queue() -> List[Dict[str, Any]]:
    """Inspect background tasks in the database task queue."""
    from ..flask.models import IndiAllSkyDbTaskQueueTable

    app = _get_flask_app()
    with app.app_context():
        tasks = IndiAllSkyDbTaskQueueTable.query.order_by(
            IndiAllSkyDbTaskQueueTable.id.desc()
        ).limit(25).all()

        results = []
        for t in tasks:
            results.append(
                {
                    "task_id": t.id,
                    "queue": str(t.queue),
                    "state": str(t.state),
                    "priority": t.priority,
                    "data": t.data or {},
                    "createDate": t.createDate.isoformat() if t.createDate else None,
                }
            )
        return results


def cancel_task(task_id: int) -> Dict[str, Any]:
    """Cancel and remove a pending or stalled task from the task queue.

    Args:
        task_id: Primary key ID of the task.

    Returns:
        Dictionary confirming task removal.
    """
    from ..flask import db
    from ..flask.models import IndiAllSkyDbTaskQueueTable

    app = _get_flask_app()
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable.query.filter(
            IndiAllSkyDbTaskQueueTable.id == int(task_id)
        ).first()

        if not task:
            return {"status": "error", "message": f"Task ID {task_id} not found."}

        db.session.delete(task)
        db.session.commit()
        return {"status": "success", "message": f"Task {task_id} canceled successfully."}



def send_notification(title: str, message: str, category: str = "general") -> Dict[str, Any]:
    """Inject a notification alert into the system for dispatch to configured channels.

    Args:
        title: Short item key or title for alert (max 32 chars).
        message: Detailed alert message.
        category: Notification category (e.g. 'general', 'camera', 'worker', 'media', 'disk', 'upload', 'state').

    Returns:
        Dictionary confirming notification creation.
    """
    from datetime import datetime, timedelta
    from ..flask import db
    from ..flask.models import IndiAllSkyDbNotificationTable, NotificationCategory

    cat_map = {
        "general": NotificationCategory.GENERAL,
        "misc": NotificationCategory.MISC,
        "camera": NotificationCategory.CAMERA,
        "worker": NotificationCategory.WORKER,
        "media": NotificationCategory.MEDIA,
        "disk": NotificationCategory.DISK,
        "upload": NotificationCategory.UPLOAD,
        "state": NotificationCategory.STATE,
    }
    cat_enum = cat_map.get(str(category).lower(), NotificationCategory.GENERAL)

    app = _get_flask_app()
    with app.app_context():
        notif = IndiAllSkyDbNotificationTable(
            item=str(title)[:32],
            category=cat_enum,
            notification=str(message)[:255],
            expireDate=datetime.now() + timedelta(days=7),
        )
        db.session.add(notif)
        db.session.commit()

        return {
            "status": "success",
            "notification_id": notif.id,
            "item": notif.item,
            "category": cat_enum.value,
            "message": notif.notification,
        }


def generate_timelapse(day_date: str, night: bool = True, camera_id: int = 1) -> Dict[str, Any]:
    """Enqueue a full nightly timelapse video generation task.

    Args:
        day_date: Target date string formatted as YYYYMMDD (e.g. '20260929').
        night: If True, renders night timelapse; otherwise daytime timelapse.
        camera_id: Camera identifier (default: 1).

    Returns:
        Dictionary confirming timelapse video generation task submission.
    """
    from ..flask import db
    from ..flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueQueue, TaskQueueState

    app = _get_flask_app()
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                "action": "generateVideo",
                "kwargs": {
                    "timespec": day_date,
                    "night": bool(night),
                    "camera_id": camera_id,
                },
            },
        )
        db.session.add(task)
        db.session.commit()

        return {
            "status": "success",
            "message": "Timelapse video generation task enqueued.",
            "task_id": task.id,
            "day_date": day_date,
            "night": bool(night),
        }


def generate_keogram_and_startrails(
    day_date: str, night: bool = True, camera_id: int = 1
) -> Dict[str, Any]:
    """Enqueue a combined keogram and star trail composite generation task.

    The underlying worker always generates both the keogram and the star trail composite
    image in a single task — they cannot be requested independently.

    Args:
        day_date: Target date string formatted as YYYYMMDD (e.g. '20260929').
        night: If True, compiles night frames; otherwise daytime frames.
        camera_id: Camera identifier (default: 1).

    Returns:
        Dictionary confirming keogram and star trails generation task submission.
    """
    from ..flask import db
    from ..flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueQueue, TaskQueueState

    app = _get_flask_app()
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                "action": "generateKeogramStarTrails",
                "kwargs": {
                    "timespec": day_date,
                    "night": bool(night),
                    "camera_id": camera_id,
                },
            },
        )
        db.session.add(task)
        db.session.commit()

        return {
            "status": "success",
            "message": "Keogram and star trails generation task enqueued.",
            "task_id": task.id,
            "day_date": day_date,
            "night": bool(night),
        }


def backup_database() -> Dict[str, Any]:
    """Trigger an immediate snapshot backup of the database via the task queue.

    Returns:
        Dictionary confirming the backup task was enqueued.
    """
    from ..flask import db
    from ..flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueQueue, TaskQueueState

    app = _get_flask_app()
    with app.app_context():
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                "action": "backupDatabase",
                "kwargs": {},
            },
        )
        db.session.add(task)
        db.session.commit()

        return {
            "status": "success",
            "message": "Database backup task enqueued.",
            "task_id": task.id,
        }


def query_media_catalog(
    media_type: str,
    camera_id: int = 1,
    limit: int = 20,
    night_only: bool = True,
    day_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query the database catalog of generated media assets.

    Args:
        media_type: Type of media — one of 'timelapse', 'keogram', 'startrails',
                    'startrails_video', or 'mini_timelapse'.
        camera_id: Camera identifier (default: 1).
        limit: Maximum number of records to return (default: 20).
        night_only: Filter to night-time media only (default: True).
        day_date: Optional date filter in 'YYYY-MM-DD' format.

    Returns:
        List of media asset metadata records.
    """
    from datetime import datetime as _dt
    from ..flask.models import (
        IndiAllSkyDbVideoTable,
        IndiAllSkyDbKeogramTable,
        IndiAllSkyDbStarTrailsTable,
        IndiAllSkyDbStarTrailsVideoTable,
        IndiAllSkyDbMiniVideoTable,
    )

    model_map = {
        "timelapse": IndiAllSkyDbVideoTable,
        "keogram": IndiAllSkyDbKeogramTable,
        "startrails": IndiAllSkyDbStarTrailsTable,
        "startrails_video": IndiAllSkyDbStarTrailsVideoTable,
        "mini_timelapse": IndiAllSkyDbMiniVideoTable,
    }

    model = model_map.get(media_type)
    if model is None:
        return [{"status": "error", "message": f"Unknown media_type '{media_type}'. Choose from: {list(model_map.keys())}"}]

    app = _get_flask_app()
    with app.app_context():
        query = model.query.filter(model.camera_id == camera_id)

        if night_only:
            query = query.filter(model.night == True)  # noqa: E712

        if day_date:
            try:
                target_date = _dt.strptime(day_date, "%Y-%m-%d").date()
                query = query.filter(model.dayDate == target_date)
            except ValueError:
                pass

        entries = query.order_by(model.createDate.desc()).limit(limit).all()

        results = []
        for e in entries:
            record: Dict[str, Any] = {
                "id": e.id,
                "filename": e.filename,
                "createDate": e.createDate.isoformat() if e.createDate else None,
                "dayDate": e.dayDate.isoformat() if e.dayDate else None,
                "night": e.night,
                "success": e.success,
                "fileSize": e.fileSize,
                "frames": getattr(e, "frames", None),
            }
            # framerate only on timelapse/mini/startrails_video
            if hasattr(e, "framerate"):
                record["framerate"] = e.framerate
            results.append(record)

        return results


def register_ops_tools(mcp_server: Any) -> None:
    """Register operational and diagnostic tools with the MCPServer instance."""
    mcp_server.tool()(get_system_logs)
    mcp_server.tool()(get_hardware_throttling)
    mcp_server.tool()(inspect_task_queue)
    mcp_server.tool()(cancel_task)
    mcp_server.tool()(send_notification)
    mcp_server.tool()(generate_timelapse)
    mcp_server.tool()(generate_keogram_and_startrails)
    mcp_server.tool()(backup_database)
    mcp_server.tool()(query_media_catalog)
