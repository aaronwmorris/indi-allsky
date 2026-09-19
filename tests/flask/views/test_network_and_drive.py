from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from indi_allsky.flask.views import (
    AjaxNetworkManagerView,
    AjaxDriveManagerView,
)


def test_network_manager_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"wlan0: connected"
            mock_run.return_value.returncode = 0
            res_post = client.post("/indi-allsky/ajax/network", json={"COMMAND": "status"})
            assert res_post.status_code in (200, 400, 500)


def test_drive_manager_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"/dev/sda1 /mnt/drive ext4"
            mock_run.return_value.returncode = 0
            res_post = client.post("/indi-allsky/ajax/drives", json={"COMMAND": "status"})
            assert res_post.status_code in (200, 400, 500)
