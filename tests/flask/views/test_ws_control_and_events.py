import json
import pytest
from unittest.mock import patch, MagicMock
import simple_websocket
from indi_allsky.flask.views import WsControlView
from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable, IndiAllSkyDbUserTable, IndiAllSkyDbCameraTable
from indi_allsky.flask import db


def test_ws_control_view_unauthorized(flask_app, system_db):
    view = WsControlView()
    with flask_app.test_request_context("/indi-allsky/ws/control"):
        with patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = False
            res, status = view.dispatch_request()
            assert status == 401


def test_ws_control_message_handling(flask_app, system_db):
    """Test WebSocket message processing loop in WsControlView."""
    view = WsControlView()

    mock_ws = MagicMock()
    # Sequence of messages sent by WS client:
    messages = [
        json.dumps({"type": "ping"}),
        json.dumps({"type": "get_status"}),
        json.dumps({"type": "get_sensors"}),
        json.dumps({"type": "reboot"}),
        json.dumps({"type": "shutdown"}),
        json.dumps({"type": "pause"}),
        json.dumps({"type": "unpause"}),
        json.dumps({"type": "reload_config"}),
        json.dumps({"type": "generate_keogram"}),
        json.dumps({"type": "generate_timelapse"}),
        json.dumps({"type": "generate_startrail"}),
        json.dumps({"type": "trigger_darks"}),
        json.dumps({"type": "start_service", "service": "indi-allsky"}),
        json.dumps({"type": "stop_service", "service": "indiserver"}),
        json.dumps({"type": "restart_service", "service": "gunicorn"}),
        "invalid json text",
        None  # End loop
    ]
    mock_ws.receive.side_effect = messages

    with flask_app.test_request_context("/indi-allsky/ws/control"):
        with patch.object(view, "rebootSystemd", side_effect=Exception("DBus reboot error")), \
             patch.object(view, "poweroffSystemd", side_effect=Exception("DBus poweroff error")), \
             patch.object(view, "startSystemdUnit", return_value=True), \
             patch.object(view, "stopSystemdUnit", side_effect=Exception("DBus stop error")), \
             patch.object(view, "restartSystemdUnit", return_value=True), \
             patch("indi_allsky.events.event_manager"):
            
            with patch("simple_websocket.Server.accept", return_value=mock_ws):
                with patch("indi_allsky.flask.views.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.is_admin = True
                    view.dispatch_request()

    # Verify WS sent multiple JSON frame responses
    assert mock_ws.send.call_count >= 14
    
    # Verify task queue entries created for DBus fallbacks and tasks
    with flask_app.app_context():
        tasks = IndiAllSkyDbTaskQueueTable.query.all()
        assert len(tasks) >= 9


def test_ws_control_connection_closed(flask_app, system_db):
    """Test WsControlView handling simple_websocket.ConnectionClosed."""
    view = WsControlView()
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = simple_websocket.ConnectionClosed(1000, "Closed")

    with flask_app.test_request_context("/indi-allsky/ws/control"):
        with patch("simple_websocket.Server.accept", return_value=mock_ws), \
             patch("indi_allsky.events.event_manager"), \
             patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = True
            mock_user.is_admin = True
            view.dispatch_request()

    mock_ws.close.assert_called()


def test_ws_shell_view(flask_app, system_db):
    from indi_allsky.flask.views import WsShellView

    view = WsShellView()

    # 1. Unauthorized network
    with flask_app.test_request_context("/indi-allsky/ws/shell"):
        with patch.object(view, "verify_admin_network", return_value=False):
            res, status = view.dispatch_request()
            assert status == 401

    # 2. Authorized connection with message handling loop
    mock_ws = MagicMock()
    messages = [
        json.dumps({"type": "input", "data": "ls\n"}),
        json.dumps({"type": "resize", "cols": 120, "rows": 40}),
        "invalid json",
        None  # End loop
    ]
    mock_ws.receive.side_effect = messages

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with flask_app.test_request_context("/indi-allsky/ws/shell"):
        with patch.object(view, "verify_admin_network", return_value=True), \
             patch("indi_allsky.flask.views.current_user", mock_user), \
             patch("simple_websocket.Server.accept", return_value=mock_ws), \
             patch("indi_allsky.flask.views.set_winsize"), \
             patch("pty.openpty", return_value=(999, 998)), \
             patch("os.close"), \
             patch("os.write"), \
             patch("select.select", return_value=([], [], [])), \
             patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            view.dispatch_request()
            mock_proc.terminate.assert_called()


def test_ws_events_view(flask_app, system_db):
    from indi_allsky.flask.views import WsEventsView

    view = WsEventsView()

    # 1. Auth required but unauthorized
    with flask_app.test_request_context("/indi-allsky/ws/events", headers={"Authorization": "Bearer badtoken"}):
        with patch.dict(flask_app.config, {"INDI_ALLSKY_AUTH_ALL_VIEWS": True, "SECRET_KEY": "goodkey"}):
            with patch("indi_allsky.flask.views.current_user") as mock_user:
                mock_user.is_authenticated = False
                res, status = view.dispatch_request()
                assert status == 401

    # 2. Handshake exception
    mock_ws_fail = MagicMock()
    mock_ws_fail.send.side_effect = Exception("Handshake error")
    with flask_app.test_request_context("/indi-allsky/ws/events"):
        with patch("simple_websocket.Server.accept", return_value=mock_ws_fail), \
             patch("indi_allsky.events.event_manager"), \
             patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = True
            res = view.dispatch_request()
            assert res == ""

    # 3. Message loop with ping, get_status, sensors, action rejection, invalid json, and exception
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = [
        json.dumps({"type": "ping"}),
        json.dumps({"type": "get_status"}),
        json.dumps({"type": "get_sensors"}),
        json.dumps({"type": "shutdown"}),
        "invalid json",
        json.dumps({"type": "custom_bad"}),
        simple_websocket.ConnectionClosed(1000, "Normal"),
    ]
    with flask_app.test_request_context("/indi-allsky/ws/events"):
        with patch("simple_websocket.Server.accept", return_value=mock_ws), \
             patch("indi_allsky.events.event_manager"), \
             patch("indi_allsky.sensors_mapping.get_latest_sensors_payload", return_value={"temp": 20}), \
             patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = True
            res = view.dispatch_request()
            assert res == ""
            assert mock_ws.send.call_count >= 4



