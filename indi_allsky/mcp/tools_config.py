"""Configuration tools for INDI Allsky MCP server."""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger('indi_allsky.mcp.config')


def _get_flask_app():
    from ..flask import create_app
    return create_app()


def get_config(section: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the active system configuration or a specific sub-dictionary.

    Args:
        section: Optional section key (e.g. 'IMAGE_STRETCH', 'CCD_CONFIG', 'SCNR_ALGORITHM').

    Returns:
        Dictionary representing the requested configuration branch or full configuration.
    """
    from ..config import IndiAllSkyConfig

    app = _get_flask_app()
    with app.app_context():
        config_obj = IndiAllSkyConfig()
        cfg = dict(config_obj.config)

        if section:
            if section in cfg:
                return {section: cfg[section]}
            raise KeyError(f"Configuration section '{section}' not found.")
        return cfg


def update_config(updates: Dict[str, Any], note: str, username: str = "admin") -> Dict[str, Any]:
    """Validate and persist updates to the INDI Allsky configuration.

    Args:
        updates: Key-value dictionary of settings to merge into active config.
        note: Descriptive reason for configuration revision.
        username: Name of user recording the change.

    Returns:
        Dictionary containing revision ID, timestamp, and status message.
    """
    from ..config import IndiAllSkyConfig
    from ..flask.models import IndiAllSkyDbUserTable
    from ..exceptions import ConfigSaveException

    app = _get_flask_app()
    with app.app_context():
        user_entry = IndiAllSkyDbUserTable.query.filter(
            IndiAllSkyDbUserTable.username == str(username)
        ).first()

        if not user_entry:
            user_entry = IndiAllSkyDbUserTable.query.filter(
                IndiAllSkyDbUserTable.is_admin == True  # noqa: E712
            ).first()

        if not user_entry:
            user_entry = IndiAllSkyDbUserTable.query.first()

        if not user_entry:
            raise ConfigSaveException("No valid database user available to record configuration.")

        config_obj = IndiAllSkyConfig()
        new_config = dict(config_obj.config)

        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(new_config.get(key), dict):
                new_config[key] = dict(new_config[key])
                new_config[key].update(value)
            else:
                new_config[key] = value

        config_obj.config = new_config
        saved_entry = config_obj.save(user_entry.username, note)

        return {
            "status": "success",
            "config_id": saved_entry.id,
            "level": saved_entry.level,
            "created_at": saved_entry.createDate.isoformat() if saved_entry.createDate else None,
            "note": saved_entry.note,
        }


def list_config_history(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve historical configuration snapshots.

    Args:
        limit: Maximum number of revisions to return (default: 10).

    Returns:
        List of configuration revision metadata records.
    """
    from ..flask.models import IndiAllSkyDbConfigTable

    app = _get_flask_app()
    with app.app_context():
        entries = (
            IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.createDate.desc())
            .limit(limit)
            .all()
        )

        history = []
        for entry in entries:
            history.append(
                {
                    "id": entry.id,
                    "level": entry.level,
                    "created_at": entry.createDate.isoformat() if entry.createDate else None,
                    "user_id": entry.user_id,
                    "note": entry.note,
                    "encrypted": entry.encrypted,
                }
            )
        return history


def rollback_config(config_id: int, note: str, username: str = "admin") -> Dict[str, Any]:
    """Roll back system configuration to a specified historical revision.

    Args:
        config_id: Target revision ID to restore.
        note: Audit note explaining the rollback.
        username: Author recording the rollback.

    Returns:
        Dictionary containing new revision ID and restored configuration metadata.
    """
    from ..config import IndiAllSkyConfig
    from ..flask.models import IndiAllSkyDbConfigTable, IndiAllSkyDbUserTable
    from ..exceptions import ConfigSaveException

    app = _get_flask_app()
    with app.app_context():
        target_entry = IndiAllSkyDbConfigTable.query.filter(
            IndiAllSkyDbConfigTable.id == int(config_id)
        ).first()

        if not target_entry:
            raise KeyError(f"Configuration revision ID {config_id} does not exist.")

        user_entry = IndiAllSkyDbUserTable.query.filter(
            IndiAllSkyDbUserTable.username == str(username)
        ).first()
        if not user_entry:
            user_entry = IndiAllSkyDbUserTable.query.first()

        if not user_entry:
            raise ConfigSaveException("No valid database user available to record configuration.")

        config_obj = IndiAllSkyConfig()
        config_obj.config = dict(target_entry.data)
        saved_entry = config_obj.save(user_entry.username, f"Rollback to revision {config_id}: {note}")

        return {
            "status": "success",
            "restored_from_id": config_id,
            "new_config_id": saved_entry.id,
            "created_at": saved_entry.createDate.isoformat() if saved_entry.createDate else None,
            "note": saved_entry.note,
        }


def register_config_tools(mcp_server: Any) -> None:
    """Register configuration tools with the MCPServer instance."""
    mcp_server.tool()(get_config)
    mcp_server.tool()(update_config)
    mcp_server.tool()(list_config_history)
    mcp_server.tool()(rollback_config)
