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
