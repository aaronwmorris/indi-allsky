"""Unit tests for MCP dark frame library tools."""

from types import SimpleNamespace
from unittest.mock import patch
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_darks import audit_dark_library


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


def test_audit_dark_library_empty(app_ctx):
    with patch("indi_allsky.flask.models.IndiAllSkyDbDarkFrameTable.query") as mock_q:
        mock_q.filter.return_value.all.return_value = []

        res = audit_dark_library()
        assert res["status"] == "success"
        assert res["total_active_darks"] == 0
        assert res["dark_bins"] == []
