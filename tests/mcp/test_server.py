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
    """Verify all toolsets are registered on the MCPServer."""
    server = create_mcp_server()
    registered_tools = [tool.name for tool in server._tool_manager.list_tools()]

    expected_tools = [
        # Config tools
        "get_config",
        "update_config",
        "list_config_history",
        "rollback_config",
        # Image tools
        "get_latest_image",
        "query_image_history",
        "get_raw_fits_catalog",
        "get_image_metadata",
        # Simulator tools
        "simulate_processing",
        "evaluate_image_quality",
        "compare_simulation_variants",
        "detect_lines_and_meteors",
        # Astrometry tools
        "solve_lens_geometry",
        "align_cardinal_directions",
        # Hardware tools (focuser removed — no real API exists)
        "get_sensor_telemetry",
        "set_capture_pause",
        # Dark tools (BPM and master dark generation removed — no real task action exists)
        "audit_dark_library",
        # Ops tools
        "get_system_logs",
        "get_hardware_throttling",
        "inspect_task_queue",
        "cancel_task",
        "send_notification",
        "generate_timelapse",
        "generate_keogram_and_startrails",
        "backup_database",
        "query_media_catalog",
        # Ephemeris & Space Weather tools
        "update_orbital_elements",
        "get_satellite_passes",
        "get_aurora_telemetry",
        "query_air_traffic",
    ]

    for tool_name in expected_tools:
        assert tool_name in registered_tools, f"Expected tool '{tool_name}' to be registered."

    # Verify removed tools are NOT registered
    removed_tools = [
        "get_focuser_position",
        "move_focuser",
        "run_autofocus_sweep",
        "control_dew_heater",
        "control_enclosure_fan",
        "generate_bad_pixel_map",
        "generate_master_darks",
        "render_keogram",
        "generate_startrails",
        "generate_custom_timelapse",
        "trigger_cloud_sync",
    ]
    for tool_name in removed_tools:
        assert tool_name not in registered_tools, f"Removed tool '{tool_name}' should not be registered."


def test_mcp_server_prompts_registered():
    """Verify prompt workflows are registered."""
    server = create_mcp_server()
    registered_prompts = [prompt.name for prompt in server._prompt_manager.list_prompts()]

    assert "optimize_image_pipeline" in registered_prompts
    assert "diagnose_capture_quality" in registered_prompts
    assert "diagnose_optics_and_focus" in registered_prompts
    assert "audit_observatory_health" in registered_prompts
    assert "diagnose_system_logs" in registered_prompts
