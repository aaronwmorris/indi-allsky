import ephem
from unittest.mock import patch, MagicMock
from indi_allsky.flask.views import AstroPanelView, AjaxAstroPanelView



def test_astro_panel_view_rendering(flask_app, system_db):
    client = flask_app.test_client()
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        res = client.get("/indi-allsky/astropanel?camera_id=1")
        assert res.status_code == 200


def test_astropanel_get_moon_phase_branches(flask_app, system_db):
    with flask_app.test_request_context("/indi-allsky/astropanel"):
        view = AjaxAstroPanelView()

        obs = MagicMock()
        obs.date = ephem.Date("2026/09/20 12:00:00")

        # Test moon phase branch calculations
        with patch("ephem.next_full_moon") as mock_full, \
             patch("ephem.previous_full_moon") as mock_pfull, \
             patch("ephem.next_new_moon") as mock_new, \
             patch("ephem.previous_new_moon") as mock_pnew, \
             patch("ephem.next_first_quarter_moon") as mock_fq, \
             patch("ephem.previous_first_quarter_moon") as mock_pfq, \
             patch("ephem.next_last_quarter_moon") as mock_lq, \
             patch("ephem.previous_last_quarter_moon") as mock_plq:

            d1 = ephem.Date("2026/09/20 12:00:00")
            mock_full.return_value = d1
            mock_pfull.return_value = d1
            mock_new.return_value = d1
            mock_pnew.return_value = d1
            mock_fq.return_value = d1
            mock_pfq.return_value = d1
            mock_lq.return_value = d1
            mock_plq.return_value = d1

            res = view.astropanel_get_moon_phase(obs)
            assert res == 'Full'


def test_astropanel_get_body_positions_exceptions(flask_app, system_db):
    with flask_app.test_request_context("/indi-allsky/astropanel"):
        view = AjaxAstroPanelView()
        obs = MagicMock()
        obs.date = ephem.now()
        obs.previous_rising.side_effect = ephem.NeverUpError
        obs.previous_transit.side_effect = ephem.NeverUpError

        body = ephem.Sun()

        pos = view.astropanel_get_body_positions(obs, body)
        assert pos == ['-', '-', '-']




