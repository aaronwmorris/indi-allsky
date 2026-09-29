"""Unit tests for MCP dark frame and BPM tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_darks import (
    audit_dark_library,
    generate_bad_pixel_map,
    generate_master_darks,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_audit_dark_library(app_ctx):
    mock_dark1 = SimpleNamespace(
        id=1,
        exposure=15.0,
        gain=100.0,
        binmode=1,
        temp=10.0,
        bitdepth=16,
        filename="/darks/dark1.fit",
    )
    with patch("indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query") as mock_q:
        mock_q.filter.return_value.all.return_value = [mock_dark1]

        res = audit_dark_library()
        assert res["status"] == "success"
        assert res["total_active_darks"] == 1
        assert res["dark_bins"][0]["exposure"] == 15.0


def test_generate_bad_pixel_map(app_ctx):
    mock_dark = SimpleNamespace(id=10, filename="/darks/dark10.fit")
    with patch("indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query") as mock_q:
        mock_q.filter.return_value.first.return_value = mock_dark

        res = generate_bad_pixel_map(dark_id=10)
        assert res["status"] == "success"
        assert res["dark_id"] == 10
        assert "total_defects" in res

    # Not found case
    with patch("indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query") as mock_q:
        mock_q.filter.return_value.first.return_value = None
        res_err = generate_bad_pixel_map(dark_id=999)
        assert res_err["status"] == "error"


def test_generate_master_darks(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = generate_master_darks(exposure=30.0, gain=120.0, temp_bin=5.0)
        assert res["status"] == "success"
        assert res["exposure"] == 30.0
        assert res["gain"] == 120.0
        assert res["temp_bin"] == 5.0
        assert mock_session.add.called
        assert mock_session.commit.called

