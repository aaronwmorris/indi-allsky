"""Unit tests for MCP image simulator tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_simulator import (
    simulate_processing,
    evaluate_image_quality,
    compare_simulation_variants,
    detect_lines_and_meteors,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_simulate_processing_not_found(app_ctx):
    with patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_q:
        mock_q.join.return_value.filter.return_value.first.return_value = None

        res = simulate_processing(fits_id=999)
        assert res["status"] == "error"
        assert "not found" in res["message"]


def test_evaluate_image_quality_success(app_ctx):
    mock_sim_return = {
        "status": "success",
        "fits_id": 1,
        "processing_elapsed_s": 0.12,
        "stars_count": 85,
        "detections_count": 0,
        "mean_background_adu": 32.0,
        "stddev_noise": 4.5,
        "min_val": 0,
        "max_val": 255,
    }

    with patch("indi_allsky.mcp.tools_simulator.simulate_processing", return_value=mock_sim_return):
        res = evaluate_image_quality(fits_id=1, config_overrides={"IMAGE_STRETCH": {"MODE1_GAMMA": 3.0}})
        assert res["status"] == "success"
        assert "quality_score" in res
        assert isinstance(res["quality_score"], float)


def test_compare_simulation_variants(app_ctx):
    mock_res1 = {
        "status": "success",
        "fits_id": 1,
        "stars_count": 100,
        "mean_background_adu": 30.0,
        "stddev_noise": 3.0,
        "quality_score": 140.0,
    }
    mock_res2 = {
        "status": "success",
        "fits_id": 1,
        "stars_count": 50,
        "mean_background_adu": 45.0,
        "stddev_noise": 8.0,
        "quality_score": 60.0,
    }

    variants = [
        {"IMAGE_STRETCH": {"MODE1_GAMMA": 2.0}},
        {"IMAGE_STRETCH": {"MODE1_GAMMA": 4.0}},
    ]

    with patch("indi_allsky.mcp.tools_simulator.evaluate_image_quality", side_effect=[mock_res2, mock_res1]):
        ranked = compare_simulation_variants(fits_id=1, variants=variants)
        assert len(ranked) == 2
        assert ranked[0]["quality_score"] >= ranked[1]["quality_score"]
        assert ranked[0]["quality_score"] == 140.0


def test_detect_lines_and_meteors(app_ctx):
    mock_sim = {
        "status": "success",
        "fits_id": 1,
        "stars_count": 45,
    }
    with patch("indi_allsky.mcp.tools_simulator.simulate_processing", return_value=mock_sim):
        res = detect_lines_and_meteors(fits_id=1)
        assert res["status"] == "success"
        assert res["detected_lines_count"] == 1
        assert res["lines"][0]["type"] == "meteor_candidate"

