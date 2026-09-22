import io
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import ephem
import pytest

from indi_allsky.flask.views import (
    StreamLogViewBase,
    StreamLogView,
    StreamIndiserverLogView,
    WsShellView,
    set_winsize,
    AjaxAstroPanelView,
)


def test_set_winsize():
    with patch("fcntl.ioctl") as mock_ioctl:
        set_winsize(1, 24, 80)
        assert mock_ioctl.called


def test_stream_log_views_generator(flask_app, system_db):
    client = flask_app.test_client()
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    # Mock systemd journal
    mock_reader = MagicMock()
    mock_reader.fileno.return_value = 5
    mock_reader.get_events.return_value = 1
    mock_reader.process.return_value = 1 # journal.APPEND
    mock_reader.__iter__.return_value = [{"MESSAGE": "Test log message"}]

    mock_poll = MagicMock()
    poll_results = [True, False]
    mock_poll.poll.side_effect = lambda *a, **k: poll_results.pop(0) if poll_results else False

    mock_journal = MagicMock()
    mock_journal.Reader.return_value = mock_reader
    mock_journal.APPEND = 1

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch.dict("sys.modules", {"systemd": MagicMock(journal=mock_journal), "systemd.journal": mock_journal}), \
         patch("select.poll", return_value=mock_poll), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        res1 = client.get("/indi-allsky/stream/log")
        assert res1.status_code == 200

        res2 = client.get("/indi-allsky/stream/indiserver_log")
        assert res2.status_code == 200


def test_ws_shell_view_permissions_and_execution(flask_app, system_db):
    mock_unauth = MagicMock()
    mock_unauth.is_authenticated = False

    mock_non_admin = MagicMock()
    mock_non_admin.is_authenticated = True
    mock_non_admin.is_admin = False

    mock_admin = MagicMock()
    mock_admin.is_authenticated = True
    mock_admin.is_admin = True

    # 1. Unauthenticated
    with patch("indi_allsky.flask.views.current_user", mock_unauth):
        with flask_app.test_request_context("/indi-allsky/ws/shell"):
            v1 = WsShellView()
            res = v1.dispatch_request()
            assert res == ('Unauthorized', 401)

    # 2. Non-admin
    with patch("indi_allsky.flask.views.current_user", mock_non_admin):
        with flask_app.test_request_context("/indi-allsky/ws/shell"):
            v2 = WsShellView()
            res = v2.dispatch_request()
            assert res == ('Unauthorized', 401)

    # 3. Non-admin network
    with patch("indi_allsky.flask.views.current_user", mock_admin), \
         patch.object(WsShellView, "verify_admin_network", return_value=False):
        with flask_app.test_request_context("/indi-allsky/ws/shell"):
            v3 = WsShellView()
            res = v3.dispatch_request()
            assert res == ('Unauthorized', 401)


def test_astropanel_view_astronomy_helpers(flask_app, system_db):
    sun = ephem.Sun()

    with flask_app.test_request_context("/indi-allsky/ajax/astropanel?camera_id=1"):
        view = AjaxAstroPanelView()

        # 1. Body positions normal
        real_obs = ephem.Observer()
        real_obs.lat = "51.5"
        real_obs.lon = "0.0"
        real_obs.elevation = 50
        real_obs.date = ephem.Date("2026/09/19 12:00:00")
        pos = view.astropanel_get_body_positions(real_obs, sun)
        assert len(pos) == 3

        # 2. Polar night (NeverUp)
        obs_never = ephem.Observer()
        obs_never.lat = "89.0"
        obs_never.lon = "0.0"
        obs_never.date = ephem.Date("2026/12/21 12:00:00")
        pos_never = view.astropanel_get_body_positions(obs_never, sun)
        assert len(pos_never) == 3

        # 3. Midnight sun (AlwaysUp)
        obs_always = ephem.Observer()
        obs_always.lat = "89.0"
        obs_always.lon = "0.0"
        obs_always.date = ephem.Date("2026/06/21 12:00:00")
        pos_always = view.astropanel_get_body_positions(obs_always, sun)
        assert len(pos_always) == 3

        # 4. Moon phases coverage
        phase = view.astropanel_get_moon_phase(real_obs)
        assert phase in [
            "Full", "New", "First Quarter", "Last Quarter",
            "Waxing Crescent", "Waxing Gibbous", "Waning Gibbous", "Waning Crescent", None
        ]

        # 5. Polaris data
        polaris_data = view.astropanel_get_polaris_data(real_obs)
        assert len(polaris_data) == 3
