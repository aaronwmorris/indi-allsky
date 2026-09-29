"""Unit tests for MCP hardware and device control tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_hardware import (
    get_focuser_position,
    move_focuser,
    get_sensor_telemetry,
    control_dew_heater,
    control_enclosure_fan,
    set_capture_pause,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_get_focuser_position(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls, \
         patch("indi_allsky.focuser.IndiAllSkyFocuserInterface") as mock_focuser_cls:
        mock_cfg = MagicMock()
        mock_cfg.config = {"FOCUSER": {"MAX_STEPS": 5000, "STEP_DELAY": 0.005}}
        mock_cfg_cls.return_value = mock_cfg

        mock_focuser = MagicMock()
        mock_focuser.getPosition.return_value = 2450
        mock_focuser_cls.return_value = mock_focuser

        res = get_focuser_position()
        assert res["status"] == "success"
        assert res["position"] == 2450
        assert res["max_steps"] == 5000


def test_move_focuser(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls, \
         patch("indi_allsky.focuser.IndiAllSkyFocuserInterface") as mock_focuser_cls:
        mock_focuser = MagicMock()
        mock_focuser_cls.return_value = mock_focuser

        res = move_focuser(steps=50, absolute=False)
        assert res["status"] == "success"
        assert res["commanded_steps"] == 50
        mock_focuser.moveRelative.assert_called_once_with(50)


def test_get_sensor_telemetry(app_ctx):
    from datetime import datetime
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


def test_control_dew_heater():
    res = control_dew_heater(duty_cycle=75, mode="manual")
    assert res["status"] == "success"
    assert res["duty_cycle"] == 75

    # Test clamping
    res_clamped = control_dew_heater(duty_cycle=150)
    assert res_clamped["duty_cycle"] == 100


def test_control_enclosure_fan():
    res = control_enclosure_fan(duty_cycle=40)
    assert res["status"] == "success"
    assert res["duty_cycle"] == 40


def test_set_capture_pause(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = set_capture_pause(pause=True)
        assert res["status"] == "success"
        assert res["pause"] is True
        assert mock_session.add.called
        assert mock_session.commit.called
