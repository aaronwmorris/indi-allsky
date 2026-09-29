"""Unit tests for INDI Allsky MCPServer initialization and registration."""

import pytest
from mcp.server.mcpserver import MCPServer

from indi_allsky.mcp.server import create_mcp_server


def test_create_mcp_server_instance():
    """Verify that create_mcp_server returns a configured MCPServer."""
    server = create_mcp_server(name="test-allsky-mcp")
    assert isinstance(server, MCPServer)
    assert server.name == "test-allsky-mcp"


def test_mcp_server_all_tools_registered():
    """Verify all toolsets across all phases are registered on the MCPServer."""
    server = create_mcp_server()
    registered_tools = [tool.name for tool in server._tool_manager.list_tools()]

    expected_tools = [
        # Phase 2 Tools
        "get_config",
        "update_config",
        "list_config_history",
        "rollback_config",
        "get_latest_image",
        "query_image_history",
        "get_raw_fits_catalog",
        "get_image_metadata",
        "simulate_processing",
        "evaluate_image_quality",
        "compare_simulation_variants",
        # Phase 3 Tools
        "solve_lens_geometry",
        "align_cardinal_directions",
        "get_focuser_position",
        "move_focuser",
        "get_sensor_telemetry",
        "control_dew_heater",
        "control_enclosure_fan",
        "set_capture_pause",
        "audit_dark_library",
        "generate_bad_pixel_map",
        # Phase 4 Tools
        "get_system_logs",
        "get_hardware_throttling",
        "inspect_task_queue",
        "cancel_task",
        "trigger_cloud_sync",
        "send_notification",
        "generate_custom_timelapse",
        "backup_database",
    ]

    for tool_name in expected_tools:
        assert tool_name in registered_tools, f"Expected tool '{tool_name}' to be registered."


def test_mcp_server_prompts_registered():
    """Verify prompt workflows are registered."""
    server = create_mcp_server()
    registered_prompts = [prompt.name for prompt in server._prompt_manager.list_prompts()]

    assert "optimize_image_pipeline" in registered_prompts
    assert "diagnose_capture_quality" in registered_prompts
