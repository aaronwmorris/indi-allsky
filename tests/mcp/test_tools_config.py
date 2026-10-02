"""Unit tests for MCP configuration tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_config import (
    get_config,
    update_config,
    list_config_history,
    rollback_config,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_get_config_full(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_cfg = MagicMock()
        mock_cfg.config = {"INDI_SERVER": "localhost", "CCD_CONFIG": {"NIGHT": {"GAIN": 100.0}}}
        mock_cfg_cls.return_value = mock_cfg

        res = get_config()
        assert res["INDI_SERVER"] == "localhost"
        assert res["CCD_CONFIG"]["NIGHT"]["GAIN"] == 100.0


def test_get_config_section(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_cfg = MagicMock()
        mock_cfg.config = {"INDI_SERVER": "localhost", "IMAGE_STRETCH": {"MODE1_GAMMA": 3.0}}
        mock_cfg_cls.return_value = mock_cfg

        res = get_config(section="IMAGE_STRETCH")
        assert "IMAGE_STRETCH" in res
        assert res["IMAGE_STRETCH"]["MODE1_GAMMA"] == 3.0

        with pytest.raises(KeyError):
            get_config(section="NON_EXISTENT_SECTION")


def test_update_config(app_ctx):
    mock_user = SimpleNamespace(id=1, username="admin", is_admin=True)
    mock_saved = SimpleNamespace(id=42, level="1.0", createDate=None, note="Update stretch")

    with patch("indi_allsky.flask.models.IndiAllSkyDbUserTable.query") as mock_user_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_user_q.filter.return_value.first.return_value = mock_user

        mock_cfg = MagicMock()
        mock_cfg.config = {"IMAGE_STRETCH": {"MODE1_GAMMA": 3.0, "MODE1_STDDEVS": 2.25}}
        mock_cfg.save.return_value = mock_saved
        mock_cfg_cls.return_value = mock_cfg

        updates = {"IMAGE_STRETCH": {"MODE1_GAMMA": 3.5}}
        res = update_config(updates=updates, note="Update stretch", username="admin")

        assert res["status"] == "success"
        assert res["config_id"] == 42
        mock_cfg.save.assert_called_once_with("admin", "Update stretch")


def test_list_config_history(app_ctx):
    mock_entry1 = SimpleNamespace(id=1, level="1.0", createDate=None, user_id=1, note="initial", encrypted=False)
    mock_entry2 = SimpleNamespace(id=2, level="1.0", createDate=None, user_id=1, note="second", encrypted=False)

    with patch("indi_allsky.flask.models.IndiAllSkyDbConfigTable.query") as mock_q:
        mock_q.order_by.return_value.limit.return_value.all.return_value = [mock_entry2, mock_entry1]

        history = list_config_history(limit=5)
        assert len(history) == 2
        assert history[0]["id"] == 2
        assert history[1]["id"] == 1


def test_rollback_config(app_ctx):
    mock_target = SimpleNamespace(id=5, data={"INDI_SERVER": "localhost", "CCD_CONFIG": {}})
    mock_user = SimpleNamespace(id=1, username="admin", is_admin=True)
    mock_saved = SimpleNamespace(id=6, level="1.0", createDate=None, note="Rollback")

    with patch("indi_allsky.flask.models.IndiAllSkyDbConfigTable.query") as mock_cfg_q, \
         patch("indi_allsky.flask.models.IndiAllSkyDbUserTable.query") as mock_user_q, \
         patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_cls:
        mock_cfg_q.filter.return_value.first.return_value = mock_target
        mock_user_q.filter.return_value.first.return_value = mock_user

        mock_cfg = MagicMock()
        mock_cfg.save.return_value = mock_saved
        mock_cfg_cls.return_value = mock_cfg

        res = rollback_config(config_id=5, note="bad tuning", username="admin")
        assert res["status"] == "success"
        assert res["restored_from_id"] == 5
        assert res["new_config_id"] == 6
