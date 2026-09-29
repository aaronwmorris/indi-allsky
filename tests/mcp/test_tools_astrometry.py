"""Unit tests for MCP astrometry and lens solver tools."""

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
    with patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_q:
        mock_q.filter.return_value.first.return_value = None

        res = solve_lens_geometry(fits_id=999)
        assert res["status"] == "error"
        assert "not found" in res["message"]


def test_solve_lens_geometry_success(app_ctx, tmp_path):
    dummy_fits = tmp_path / "test.fit"
    dummy_fits.write_bytes(b"FITS_DUMMY_DATA")

    mock_entry = SimpleNamespace(
        id=1,
        getLocalOrCachedPath=lambda: dummy_fits,
    )

    mock_solved = {
        "focal_length": 2.1,
        "fov_deg": 185.0,
        "offset_x": 12,
        "offset_y": -4,
        "azimuth": 178.5,
        "altitude": 89.2,
        "matched_stars": 54,
        "residual": 0.35,
    }

    with patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls, \
         patch("indi_allsky.lens_solver.solver.IndiAllSkyLensSolver") as mock_solver_cls:
        mock_q.filter.return_value.first.return_value = mock_entry
        mock_cfg = MagicMock()
        mock_cfg.config = {}
        mock_cfg_cls.return_value = mock_cfg

        mock_solver = MagicMock()
        mock_solver.solve.return_value = mock_solved
        mock_solver_cls.return_value = mock_solver

        res = solve_lens_geometry(fits_id=1)
        assert res["status"] == "success"
        assert res["focal_length"] == 2.1
        assert res["lens_azimuth"] == 178.5
        assert res["matched_stars"] == 54


def test_align_cardinal_directions(app_ctx):
    mock_solve = {
        "status": "success",
        "fits_id": 1,
        "lens_azimuth": 179.2,
    }
    with patch("indi_allsky.mcp.tools_astrometry.solve_lens_geometry", return_value=mock_solve):
        res = align_cardinal_directions(fits_id=1)
        assert res["status"] == "success"
        assert res["true_north_azimuth"] == 179.2
