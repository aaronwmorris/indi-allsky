"""Unit tests for MCP astrometry and lens solver tools."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_astrometry import (
    solve_lens_geometry,
    align_cardinal_directions,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_solve_lens_geometry_not_found(app_ctx):
    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_q:
        mock_q.filter.return_value.first.return_value = None

        res = solve_lens_geometry(image_id=999)
        assert res["status"] == "error"
        assert "not found" in res["message"]


def test_solve_lens_geometry_file_missing(app_ctx, tmp_path):
    """Image entry exists in DB but file is absent on disk."""
    nonexistent = tmp_path / "missing.jpg"

    mock_entry = SimpleNamespace(
        id=2,
        camera=None,
        binmode=1,
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        getLocalOrCachedPath=lambda: nonexistent,
    )
    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_q.filter.return_value.first.return_value = mock_entry
        mock_cfg = MagicMock()
        mock_cfg.config = {"VIRTUALSKY": {}, "LATITUDE": -34.0, "LONGITUDE": 138.0}
        mock_cfg_cls.return_value = mock_cfg

        res = solve_lens_geometry(image_id=2)
        assert res["status"] == "error"
        assert "does not exist" in res["message"]


def test_solve_lens_geometry_success(app_ctx, tmp_path):
    dummy_img = tmp_path / "test.jpg"
    dummy_img.write_bytes(b"JPEG_DUMMY_DATA")

    mock_camera = SimpleNamespace(width=1920, height=1080)
    mock_entry = SimpleNamespace(
        id=1,
        camera=mock_camera,
        binmode=1,
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        getLocalOrCachedPath=lambda: dummy_img,
    )

    mock_solved = {
        "success": True,
        "fov_deg": 185.0,
        "values": {
            "AZIMUTH_ANGLE": 178.5,
            "OFFSET_X": 12,
            "OFFSET_Y": -4,
            "LENS_ALTITUDE": 89.2,
        },
        "quality": {
            "stars_matched": 54,
            "rms_px": 0.35,
        },
        "geometry": {
            "rotation_deg": 178.5,
        },
        "message": "Matched 54 stars, RMS 0.35 px",
        "timing": {"total_s": 1.2},
    }

    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls, \
         patch("indi_allsky.lens_solver.solver.IndiAllSkyLensSolver") as mock_solver_cls:
        mock_q.filter.return_value.first.return_value = mock_entry

        mock_cfg = MagicMock()
        mock_cfg.config = {
            "VIRTUALSKY": {
                "CALIBRATION_ENABLED": False,
                "OFFSET_X": 0,
                "OFFSET_Y": 0,
                "IMAGE_CIRCLE_DIAMETER": 3500,
                "LATITUDE_OFFSET": 0.0,
                "LONGITUDE_OFFSET": 0.0,
                "PRECESSION": False,
                "RADIAL_DISTORTION": 0.0,
                "POINTING_AZIMUTH": 0.0,
            },
            "LATITUDE": -34.0,
            "LONGITUDE": 138.0,
            "LENS_AZIMUTH": 0.0,
            "LENS_ALTITUDE": 90.0,
            "LENS_OFFSET_X": 0,
            "LENS_OFFSET_Y": 0,
            "LENS_FOCAL_LENGTH": 2.5,
        }
        mock_cfg_cls.return_value = mock_cfg

        mock_solver = MagicMock()
        mock_solver.solve.return_value = mock_solved
        mock_solver_cls.return_value = mock_solver

        res = solve_lens_geometry(image_id=1)
        assert res["status"] == "success"
        assert res["lens_azimuth"] == 178.5
        assert res["matched_stars"] == 54
        assert res["residual_error"] == 0.35
        assert res["lens_offset_x"] == 12
        assert res["lens_offset_y"] == -4

        # Verify solver was called with correct initial_values structure
        call_kwargs = mock_solver.solve.call_args
        args = call_kwargs[0]
        assert "CALIBRATION_ENABLED" in args[4]
        assert "AZIMUTH_ANGLE" in args[4]
        assert "IMAGE_CIRCLE_DIAMETER" in args[4]


def test_solve_lens_geometry_failure_handled(app_ctx, tmp_path):
    dummy_img = tmp_path / "test.jpg"
    dummy_img.write_bytes(b"JPEG_DUMMY_DATA")

    mock_camera = SimpleNamespace(width=1920, height=1080)
    mock_entry = SimpleNamespace(
        id=3,
        camera=mock_camera,
        binmode=1,
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        getLocalOrCachedPath=lambda: dummy_img,
    )

    mock_failed = {
        "success": False,
        "reason": "too_few_stars",
        "message": "Only 3 stars detected -- sky may be cloudy.",
        "quality": {"stars_detected": 3, "stars_matched": 0},
    }

    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls, \
         patch("indi_allsky.lens_solver.solver.IndiAllSkyLensSolver") as mock_solver_cls:
        mock_q.filter.return_value.first.return_value = mock_entry

        mock_cfg = MagicMock()
        mock_cfg.config = {"VIRTUALSKY": {}}
        mock_cfg_cls.return_value = mock_cfg

        mock_solver = MagicMock()
        mock_solver.solve.return_value = mock_failed
        mock_solver_cls.return_value = mock_solver

        res = solve_lens_geometry(image_id=3)
        assert res["status"] == "error"
        assert "cloudy" in res["message"]


def test_align_cardinal_directions(app_ctx):
    mock_solve = {
        "status": "success",
        "image_id": 1,
        "lens_azimuth": 179.2,
    }
    with patch("indi_allsky.mcp.tools_astrometry.solve_lens_geometry", return_value=mock_solve):
        res = align_cardinal_directions(image_id=1)
        assert res["status"] == "success"
        assert res["true_north_azimuth"] == 179.2
