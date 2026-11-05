"""Unit tests for MCP ephemeris, satellite tracking, space weather, and air traffic tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import datetime
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_ephemeris import (
    update_orbital_elements,
    get_satellite_passes,
    get_aurora_telemetry,
    query_air_traffic,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_update_orbital_elements(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig"), \
         patch("indi_allsky.satellite_download.IndiAllskyUpdateSatelliteData") as mock_updater_cls:
        mock_updater = MagicMock()
        mock_updater.update.return_value = True
        mock_updater_cls.return_value = mock_updater

        res = update_orbital_elements(force=True)
        assert res["status"] == "success"
        assert res["updated"] is True
        assert res["forced"] is True


def test_get_satellite_passes(app_ctx):
    mock_sat = SimpleNamespace(
        id=1,
        title="ISS (ZARYA)",
        group=1,
        line1="1 25544U 98067A   26272.50000000  .00016717  00000-0  10270-3 0  9002",
        line2="2 25544  51.6400 208.1000 0001234  85.0000 275.0000 15.49000000123456",
    )
    with patch("indi_allsky.flask.models.IndiAllSkyDbTleDataTable.query") as mock_q:
        mock_q.limit.return_value.all.return_value = [mock_sat]

        res = get_satellite_passes(hours_ahead=6, min_elevation=30.0)
        assert res["status"] == "success"
        assert res["tracked_count"] == 1
        assert res["satellites"][0]["title"] == "ISS (ZARYA)"
        assert res["satellites"][0]["name"] == "ISS (ZARYA)"


def test_get_aurora_telemetry_with_data(app_ctx):
    mock_image = SimpleNamespace(
        kpindex=4.33,
        ovation_max=35,
        createDate=datetime(2026, 9, 29, 2, 0, 0),
    )
    mock_state = SimpleNamespace(value="480.2")

    with patch("indi_allsky.config.IndiAllSkyConfig"), \
         patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_img_q, \
         patch("indi_allsky.flask.models.IndiAllSkyDbStateTable.query") as mock_state_q:
        mock_img_q.order_by.return_value.first.return_value = mock_image
        mock_state_q.filter_by.return_value.first.return_value = mock_state

        res = get_aurora_telemetry()
        assert res["status"] == "success"
        assert res["kp_index"] == 4.33
        assert res["ovation_max_percent"] == 35
        assert res["solar_wind_speed_km_s"] == 480.2
        assert res["aurora_active"] is True


def test_get_aurora_telemetry_empty(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig"), \
         patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_img_q, \
         patch("indi_allsky.flask.models.IndiAllSkyDbStateTable.query") as mock_state_q:
        mock_img_q.order_by.return_value.first.return_value = None
        mock_state_q.filter_by.return_value.first.return_value = None

        res = get_aurora_telemetry()
        assert res["status"] == "success"
        assert res["kp_index"] is None
        assert res["ovation_max_percent"] is None
        assert res["solar_wind_speed_km_s"] is None
        assert res["aurora_active"] is False


def test_query_air_traffic_disabled(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_cfg = MagicMock()
        mock_cfg.config = {"ADSB": {"ENABLE": False}}
        mock_cfg_cls.return_value = mock_cfg

        res = query_air_traffic()
        assert res["status"] == "success"
        assert res["adsb_enabled"] is False
        assert res["aircraft_count"] == 0
        assert "disabled" in res["message"].lower()


def test_query_air_traffic_no_url(app_ctx):
    """Enabled but no DUMP1090_URL configured — should return not configured message."""
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_cfg = MagicMock()
        mock_cfg.config = {"ADSB": {"ENABLE": True}}
        mock_cfg_cls.return_value = mock_cfg

        res = query_air_traffic()
        assert res["status"] == "success"
        assert res["aircraft_count"] == 0
