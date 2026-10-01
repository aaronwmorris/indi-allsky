import os
import json
import time
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
import ephem

from indi_allsky.flask.models import db, IndiAllSkyDbTaskQueueTable
from indi_allsky.flask.views import (
    AjaxAstroPanelView,
    WsShellView,
    WsEventsView,
    WsControlView,
    set_winsize,
)


def test_astropanel_moon_phase_and_body_positions(flask_app, system_db):
    """Test astropanel moon phase classifications and astronomical body position branches."""
    view = AjaxAstroPanelView()
    obs = MagicMock()
    obs.lat = "51.5"
    obs.lon = 0.0
    obs.elevation = 50
    obs.horizon = 0

    # 1. Moon phase tests
    with patch("ephem.localtime") as mock_local:
        obs.date = ephem.Date("2026/09/21 12:00:00")

        d_today = datetime(2026, 9, 21).date()
        d_other1 = datetime(2026, 9, 15).date()

        # Moon phase: New
        mock_local.side_effect = lambda d: MagicMock(date=lambda: d_today if d == "new" else d_other1)
        with patch("ephem.next_new_moon", return_value="new"):
            with patch("ephem.previous_new_moon", return_value="new"):
                with patch("ephem.next_full_moon", return_value="other"):
                    with patch("ephem.previous_full_moon", return_value="other"):
                        with patch("ephem.next_first_quarter_moon", return_value="other"):
                            with patch("ephem.previous_first_quarter_moon", return_value="other"):
                                with patch("ephem.next_last_quarter_moon", return_value="other"):
                                    with patch("ephem.previous_last_quarter_moon", return_value="other"):
                                        phase = view.astropanel_get_moon_phase(obs)
                                        assert phase in ("New", "Full", "First Quarter", "Last Quarter", "Waxing Crescent", "Waxing Gibbous", "Waning Gibbous", "Waning Crescent")

    # 2. Body positions: AlwaysUpError / NeverUpError handling
    sun = ephem.Sun()
    now_utc = datetime.now(tz=timezone.utc)
    obs.previous_rising.side_effect = ephem.AlwaysUpError
    obs.previous_transit.return_value = now_utc - timedelta(hours=2)
    with patch("ephem.localtime", return_value=datetime(2026, 9, 21)):
        pos = view.astropanel_get_body_positions(obs, sun)
        assert pos[0] == "-"
        assert pos[2] == "-"

    # 3. Sun twilights AlwaysUpError handling
    with patch.object(view, "astropanel_get_body_positions", side_effect=ephem.AlwaysUpError):
        twilights = view.astropanel_get_sun_twilights(obs, sun)
        assert twilights == [("n/a", "n/a"), ("n/a", "n/a"), ("n/a", "n/a")]

    # 4. Polaris data calculation and AlwaysUpError transit
    obs.date = ephem.Date("2026/09/21 00:00:00")
    obs.next_transit.side_effect = ephem.AlwaysUpError
    mock_polaris = MagicMock()
    mock_polaris.ra = 0.5
    mock_polaris.alt = 45.0
    with patch("ephem.readdb", return_value=mock_polaris):
        polaris_data = view.astropanel_get_polaris_data(obs)
        assert polaris_data[1] == "-"
        assert polaris_data[2] == 45.0


def test_ws_shell_view_permissions_and_messages(flask_app, system_db):
    """Test WsShellView permissions, pty read thread, and command handling."""
    view = WsShellView()

    # 1. Unauthenticated -> 401
    mock_unauth = MagicMock(is_authenticated=False)
    with flask_app.test_request_context():
        with patch("indi_allsky.flask.views.current_user", mock_unauth):
            res, code = view.dispatch_request()
            assert code == 401

    # 2. Non-admin -> 401
    mock_nonadmin = MagicMock(is_authenticated=True, is_admin=False)
    with flask_app.test_request_context():
        with patch("indi_allsky.flask.views.current_user", mock_nonadmin):
            res, code = view.dispatch_request()
            assert code == 401

    # 3. Non-admin network -> 401
    mock_admin = MagicMock(is_authenticated=True, is_admin=True)
    with flask_app.test_request_context():
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            with patch.object(view, "verify_admin_network", return_value=False):
                res, code = view.dispatch_request()
                assert code == 401

    # 4. WebSocket input and resize handling
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = [
        json.dumps({"type": "input", "data": "ls -la\n"}),
        json.dumps({"type": "resize", "cols": 80, "rows": 24}),
        None,  # Close connection
    ]

    mock_proc = MagicMock()
    with flask_app.test_request_context():
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            with patch.object(view, "verify_admin_network", return_value=True):
                with patch("simple_websocket.Server.accept", return_value=mock_ws):
                    with patch("pty.openpty", return_value=(10, 11)):
                        with patch("subprocess.Popen", return_value=mock_proc):
                            with patch("os.close"):
                                with patch("os.write") as mock_write:
                                    with patch("indi_allsky.flask.views.set_winsize") as mock_set_win:
                                        res = view.dispatch_request()
                                        assert res == ""
                                        mock_write.assert_called()
                                        mock_set_win.assert_called_with(10, 24, 80)


def test_ws_events_and_control_views_messages(flask_app, system_db):
    """Test WsEventsView and WsControlView websocket dispatch and command queues."""
    # 1. WsEventsView: ping, get_status, get_sensors, command rejection
    events_view = WsEventsView()
    mock_ws = MagicMock()
    mock_ws.receive.side_effect = [
        json.dumps({"type": "ping"}),
        json.dumps({"type": "get_status"}),
        json.dumps({"type": "get_sensors"}),
        json.dumps({"type": "reboot"}),  # Should be rejected on read-only endpoint
        None,
    ]

    with flask_app.test_request_context():
        with patch("simple_websocket.Server.accept", return_value=mock_ws):
            with patch("indi_allsky.events.event_manager.register"):
                with patch("indi_allsky.events.event_manager.unregister"):
                    res = events_view.dispatch_request()
                    assert res == ""
                    assert mock_ws.send.call_count >= 4

    # 2. WsControlView: reboot, task queuing, service commands
    control_view = WsControlView()
    mock_control_ws = MagicMock()
    mock_control_ws.receive.side_effect = [
        json.dumps({"type": "reboot"}),
        json.dumps({"type": "pause"}),
        json.dumps({"type": "restart_service", "service": "indiserver"}),
        None,
    ]

    mock_admin = MagicMock(is_authenticated=True, is_admin=True)
    with flask_app.test_request_context():
        with patch("indi_allsky.flask.views.current_user", mock_admin):
            with patch("simple_websocket.Server.accept", return_value=mock_control_ws):
                with patch("indi_allsky.events.event_manager.register"):
                    with patch("indi_allsky.events.event_manager.unregister"):
                        with patch.object(control_view, "rebootSystemd", side_effect=Exception("DBus unavailable")):
                            with patch.object(control_view, "restartSystemdUnit", side_effect=Exception("DBus unavailable")):
                                res = control_view.dispatch_request()
                                assert res == ""
                                assert mock_control_ws.send.call_count >= 3
