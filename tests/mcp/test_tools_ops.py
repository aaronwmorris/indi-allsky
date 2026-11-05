"""Unit tests for MCP operations, log streaming, and media tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch
from datetime import datetime
import pytest

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_ops import (
    get_system_logs,
    get_hardware_throttling,
    inspect_task_queue,
    cancel_task,
    send_notification,
    generate_timelapse,
    generate_keogram_and_startrails,
    backup_database,
    query_media_catalog,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_get_system_logs():
    mock_data = "line 1\nline 2 error detected\nline 3\n"
    with patch("indi_allsky.mcp.tools_ops.Path.is_file", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_data)):
        res = get_system_logs(log_type="app", lines=2)
        assert res["status"] == "success"
        assert len(res["lines"]) == 2


def test_get_hardware_throttling():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "throttled=0x50000\n"

    with patch("subprocess.run", return_value=mock_proc):
        res = get_hardware_throttling()
        assert res["status"] == "success"
        assert res["throttled"] is True
        assert res["raw_flags"] == "0x50000"


def test_inspect_task_queue(app_ctx):
    mock_task = SimpleNamespace(
        id=12,
        queue="main",
        state="pending",
        priority=50,
        data={"action": "test"},
        createDate=datetime(2026, 9, 29, 12, 0, 0),
    )
    with patch("indi_allsky.flask.models.IndiAllSkyDbTaskQueueTable.query") as mock_q:
        mock_q.order_by.return_value.limit.return_value.all.return_value = [mock_task]

        res = inspect_task_queue()
        assert len(res) == 1
        assert res[0]["task_id"] == 12


def test_cancel_task(app_ctx):
    mock_task = SimpleNamespace(id=12)
    with patch("indi_allsky.flask.models.IndiAllSkyDbTaskQueueTable.query") as mock_q, \
         patch("indi_allsky.flask.db.session") as mock_session:
        mock_q.filter.return_value.first.return_value = mock_task

        res = cancel_task(task_id=12)
        assert res["status"] == "success"
        mock_session.delete.assert_called_once_with(mock_task)
        assert mock_session.commit.called


def test_send_notification(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = send_notification(title="Fireball", message="Bright meteor detected", category="general")
        assert res["status"] == "success"
        assert res["item"] == "Fireball"
        assert mock_session.add.called
        assert mock_session.commit.called


def test_generate_timelapse(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = generate_timelapse(day_date="20260929", night=True)
        assert res["status"] == "success"
        assert res["day_date"] == "20260929"
        assert res["night"] is True
        assert mock_session.add.called
        assert mock_session.commit.called


def test_generate_keogram_and_startrails(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = generate_keogram_and_startrails(day_date="20260929", night=True)
        assert res["status"] == "success"
        assert res["day_date"] == "20260929"
        assert res["night"] is True
        assert mock_session.add.called
        assert mock_session.commit.called


def test_backup_database(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = backup_database()
        assert res["status"] == "success"
        assert "task_id" in res
        assert mock_session.add.called
        assert mock_session.commit.called


def test_query_media_catalog_invalid_type(app_ctx):
    res = query_media_catalog(media_type="invalid_type")
    assert len(res) == 1
    assert res[0]["status"] == "error"
    assert "Unknown media_type" in res[0]["message"]


def test_query_media_catalog_timelapse(app_ctx):
    mock_entry = SimpleNamespace(
        id=5,
        filename="/videos/video.mp4",
        createDate=datetime(2026, 9, 29, 3, 0, 0),
        dayDate=datetime(2026, 9, 29).date(),
        night=True,
        success=True,
        fileSize=102400,
        frames=1800,
        framerate=25.0,
    )
    with patch("indi_allsky.flask.models.IndiAllSkyDbVideoTable.query") as mock_q:
        mock_q.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_entry]
        res = query_media_catalog(media_type="timelapse")
        assert isinstance(res, list)
