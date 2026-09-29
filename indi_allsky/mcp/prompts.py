"""MCP Prompts for INDI Allsky."""

from typing import Any


def register_prompts(mcp_server: Any) -> None:
    """Register MCP prompt templates with the MCPServer instance."""

    @mcp_server.prompt()
    def optimize_image_pipeline(sky_condition: str = "moonless_dark_sky") -> str:
        """Prompt to guide autonomous image processing tuning."""
        return (
            f"You are optimizing INDI Allsky image processing parameters for condition: '{sky_condition}'.\n"
            "Follow these systematic steps:\n"
            "1. Call `get_config(section='IMAGE_STRETCH')` and inspect current stretching & noise parameters.\n"
            "2. Call `get_raw_fits_catalog(limit=5)` to select representative raw FITS frames.\n"
            "3. Use `compare_simulation_variants` on a sample FITS image to test combinations of:\n"
            "   - IMAGE_STRETCH Mode (MODE1_GAMMA vs MODE2_MIDTONES vs MODE3_MIDTONES & MODE3_BLACK_CLIP)\n"
            "   - CLAHE_CLIPLIMIT (1.5, 2.5, 3.5)\n"
            "   - SCNR_MTF_MIDTONES (0.5, 0.65, 0.75)\n"
            "   - IMAGE_DENOISE_STRENGTH / BILATERAL_SIGMA_COLOR\n"
            "4. Analyze the quality scores, star count yield, and background noise floor.\n"
            "5. Call `update_config` with the optimal parameter dictionary and an audit note explaining the tuning rationale."
        )

    @mcp_server.prompt()
    def diagnose_capture_quality() -> str:
        """Prompt to evaluate system capture health and star detection fidelity."""
        return (
            "You are diagnosing INDI Allsky capture quality and star detection fidelity.\n"
            "1. Read `allsky://camera/status` and `allsky://images/latest` resources.\n"
            "2. Query recent image history via `query_image_history(limit=10)`.\n"
            "3. Identify anomalies in star count, ADU levels, or detection rates.\n"
            "4. Run `evaluate_image_quality` on the latest raw FITS frames to measure SNR and FWHM.\n"
            "5. Report findings and suggest configuration adjustments or hardware maintenance (e.g. focuser adjustments or dome cleaning)."
        )

    @mcp_server.prompt()
    def diagnose_optics_and_focus() -> str:
        """Prompt to diagnose optical alignment, field rotation, and focus curve state."""
        return (
            "You are diagnosing optical alignment, True North cardinal orientation, and focuser state.\n"
            "1. Call `get_raw_fits_catalog(limit=3)` to obtain recent clear night frames.\n"
            "2. Execute `solve_lens_geometry` to determine optical focal length, field-of-view, and center offsets.\n"
            "3. Call `align_cardinal_directions` to derive True North alignment error.\n"
            "4. Read `get_focuser_position` and examine star sharpness.\n"
            "5. If defocusing or tilt is detected, recommend target focuser step movement via `move_focuser` or `run_autofocus_sweep`."
        )

    @mcp_server.prompt()
    def audit_observatory_health() -> str:
        """Prompt to inspect dark frame library, environmental metrics, and storage quotas."""
        return (
            "You are auditing observatory environmental health and calibration library coverage.\n"
            "1. Read `allsky://telemetry/environment` and check ambient temperature, humidity, and dew point.\n"
            "2. Inspect dark frame library coverage gaps using `audit_dark_library`.\n"
            "3. Check hardware throttling state using `get_hardware_throttling`.\n"
            "4. Inspect pending operations using `inspect_task_queue`.\n"
            "5. If temperature bins lack dark calibration, trigger `generate_master_darks` or adjust dew heater power via `control_dew_heater`."
        )

    @mcp_server.prompt()
    def diagnose_system_logs() -> str:
        """Prompt to review system logs for hardware driver or connection errors."""
        return (
            "You are diagnosing INDI Allsky system logs for hardware or communication faults.\n"
            "1. Call `get_system_logs(log_type='app', lines=100)` to review recent daemon messages.\n"
            "2. Call `get_system_logs(log_type='indiserver', lines=100)` to detect USB disconnects or driver crashes.\n"
            "3. Check `get_hardware_throttling` for undervoltage or CPU thermal throttling.\n"
            "4. Propose remedial steps or trigger a notification alert via `send_notification`."
        )

