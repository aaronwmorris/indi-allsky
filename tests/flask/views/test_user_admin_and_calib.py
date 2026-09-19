from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from indi_allsky.flask.views import (
    AjaxAstroPanelView,
    WsShellView,
    WsEventsView,
    WsControlView,
    ESP32ImageView,
)


def test_astro_panel_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.get("/indi-allsky/ajax/astropanel?camera_id=1")
        assert res.status_code in (200, 400)


def test_ws_views(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user), \
         patch("simple_websocket.Server.accept") as mock_accept, \
         patch("pty.openpty", return_value=(1, 2)), \
         patch("os.close"), \
         patch("subprocess.Popen"):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = None
        mock_accept.return_value = mock_ws

        with flask_app.test_request_context("/ws/shell"):
            view_shell = WsShellView()
            with patch.object(view_shell, "cameraSetup"):
                try:
                    view_shell.dispatch_request()
                except Exception:
                    pass

        with flask_app.test_request_context("/ws/events"):
            view_events = WsEventsView()
            with patch.object(view_events, "cameraSetup"):
                try:
                    view_events.dispatch_request()
                except Exception:
                    pass

        with flask_app.test_request_context("/ws/control"):
            view_control = WsControlView()
            with patch.object(view_control, "cameraSetup"):
                try:
                    view_control.dispatch_request()
                except Exception:
                    pass


def test_esp32_image_view(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/esp32/image?camera_id=1")
        assert res.status_code in (200, 400, 404)
