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
    trigger_cloud_sync,
    send_notification,
    generate_custom_timelapse,
    backup_database,
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


def test_trigger_cloud_sync(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = trigger_cloud_sync()
        assert res["status"] == "success"
        assert mock_session.add.called
        assert mock_session.commit.called


def test_send_notification(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = send_notification(title="Fireball", message="Bright meteor detected", category="alert")
        assert res["status"] == "success"
        assert res["item"] == "Fireball"
        assert mock_session.add.called
        assert mock_session.commit.called


def test_generate_custom_timelapse(app_ctx):
    with patch("indi_allsky.flask.db.session") as mock_session:
        res = generate_custom_timelapse(
            start_dt="2026-09-29T02:00:00",
            end_dt="2026-09-29T02:30:00",
            fps=30,
        )
        assert res["status"] == "success"
        assert res["fps"] == 30
        assert mock_session.add.called
        assert mock_session.commit.called


def test_backup_database(app_ctx):
    with patch("indi_allsky.config.IndiAllSkyConfig"), \
         patch("indi_allsky.backup.IndiAllskyDatabaseBackup") as mock_backup_cls:
        mock_runner = MagicMock()
        mock_runner.db_backup.return_value = "/tmp/backup_indi-allsky.sqlite"
        mock_backup_cls.return_value = mock_runner

        res = backup_database()
        assert res["status"] == "success"
        assert "backup_indi-allsky.sqlite" in res["backup_file"]
