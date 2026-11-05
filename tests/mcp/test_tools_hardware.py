"""Unit tests for MCP hardware and device control tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import datetime
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_hardware import (
    get_sensor_telemetry,
    set_capture_pause,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_get_sensor_telemetry(app_ctx):
    mock_image = SimpleNamespace(
        sqm=21.4,
        temp=12.5,
        createDate=datetime(2026, 9, 29, 2, 0, 0),
    )
    with patch("indi_allsky.config.IndiAllSkyConfig"), \
         patch("indi_allsky.sensors_mapping.get_latest_sensors_payload") as mock_payload, \
         patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_img_q:
        mock_img_q.order_by.return_value.first.return_value = mock_image
        mock_payload.return_value = {
            "last_update": "2026-09-29 02:00:00",
            "last_update_age_s": 10,
            "sensors": {"temp_sensor_a": {"value": 14.0, "unit": "°C"}},
        }

        res = get_sensor_telemetry()
        assert res["status"] == "success"
        assert res["sqm"] == 21.4
        assert res["sensor_temperature"] == 12.5
        assert "temp_sensor_a" in res["sensors"]


def test_set_capture_pause(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = set_capture_pause(pause=True)
        assert res["status"] == "success"
        assert res["pause"] is True
        assert mock_session.add.called
        assert mock_session.commit.called


def test_set_capture_resume(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = set_capture_pause(pause=False)
        assert res["status"] == "success"
        assert res["pause"] is False
