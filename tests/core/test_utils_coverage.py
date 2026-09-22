from datetime import datetime, timedelta
from multiprocessing import Array
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.utils import IndiAllSkyDateCalcs


@pytest.fixture
def date_calcs():
    config = {'NIGHT_SUN_ALT_DEG': -6.0}
    position_av = Array('d', [0.0, 0.0, 0.0, 0.0, 0.0])
    return IndiAllSkyDateCalcs(config, position_av)


def test_calc_day_date_post_antimeridian_night(date_calcs):
    t_now = datetime(2025, 6, 1, 23, 30, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now.replace(tzinfo=None) - utc_offset

    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls:
        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun

        # night is True
        mock_sun.alt = -1.0

        mock_obs.previous_antitransit.return_value.datetime.return_value = utcnow_notz - timedelta(hours=20)
        mock_obs.next_transit.return_value.datetime.return_value = utcnow_notz - timedelta(hours=10)
        # next_antimeridian is BEFORE utcnow_notz, so utcnow_notz >= next_antimeridian
        mock_obs.next_antitransit.return_value.datetime.return_value = utcnow_notz - timedelta(minutes=10)

        day_date = date_calcs.calcDayDate(t_now)
        assert day_date == t_now.date()


def test_calc_day_date_post_antimeridian_day(date_calcs):
    t_now = datetime(2025, 6, 1, 23, 30, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now.replace(tzinfo=None) - utc_offset

    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls:
        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun

        # night is False
        mock_sun.alt = 0.5

        mock_obs.previous_antitransit.return_value.datetime.return_value = utcnow_notz - timedelta(hours=20)
        mock_obs.next_transit.return_value.datetime.return_value = utcnow_notz - timedelta(hours=10)
        mock_obs.next_antitransit.return_value.datetime.return_value = utcnow_notz - timedelta(minutes=10)

        day_date = date_calcs.calcDayDate(t_now)
        assert day_date == (t_now + timedelta(days=1)).date()


def test_calc_day_date_pre_meridian_night(date_calcs):
    """Test line 318: pre-meridian with night=True."""
    t_now = datetime(2025, 6, 1, 9, 0, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now.replace(tzinfo=None) - utc_offset

    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls:
        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun

        # night is True
        mock_sun.alt = -1.0

        mock_obs.previous_antitransit.return_value.datetime.return_value = utcnow_notz - timedelta(hours=9)
        mock_obs.next_transit.return_value.datetime.return_value = utcnow_notz + timedelta(hours=3)
        mock_obs.next_antitransit.return_value.datetime.return_value = utcnow_notz + timedelta(hours=15)

        day_date = date_calcs.calcDayDate(t_now)
        assert day_date == (t_now - timedelta(days=1)).date()



def test_get_next_day_night_transition_pre_antimeridian(date_calcs):
    t_now = datetime(2025, 6, 1, 0, 30, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now - utc_offset

    # Pre-antimeridian: utcnow_notz < previous_antimeridian
    # Case A: night = True
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = -1.0  # night

        t_prev_anti = utcnow_notz + timedelta(hours=1)
        t_today_meridian = utcnow_notz + timedelta(hours=11)
        t_next_meridian = utcnow_notz + timedelta(hours=35)
        t_next_anti = utcnow_notz + timedelta(hours=23)
        t_next_anti_2 = utcnow_notz + timedelta(hours=47)

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None

    # Case B: night = False
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = 0.5  # day

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None


def test_get_next_day_night_transition_post_meridian_and_post_antimeridian(date_calcs):
    t_now = datetime(2025, 6, 1, 14, 0, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now - utc_offset

    # Post-meridian: today_meridian <= utcnow_notz < next_antimeridian
    # Case A: night = True
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = -1.0  # night

        t_prev_anti = utcnow_notz - timedelta(hours=14)
        t_today_meridian = utcnow_notz - timedelta(hours=2)
        t_next_meridian = utcnow_notz + timedelta(hours=22)
        t_next_anti = utcnow_notz + timedelta(hours=10)
        t_next_anti_2 = utcnow_notz + timedelta(hours=34)

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None

    # Case B: night = False (hits line 405: day_stop = next_antimeridian)
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = 0.5  # day

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None

    # Post-antimeridian: utcnow_notz >= next_antimeridian (hits lines 408-409)
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = -1.0

        t_prev_anti = utcnow_notz - timedelta(hours=20)
        t_today_meridian = utcnow_notz - timedelta(hours=10)
        t_next_meridian = utcnow_notz + timedelta(hours=14)
        t_next_anti = utcnow_notz - timedelta(hours=1)
        t_next_anti_2 = utcnow_notz + timedelta(hours=23)

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None


def test_get_next_day_night_transition_pre_meridian(date_calcs):
    """Test lines 389-397: previous_antimeridian <= utcnow_notz < today_meridian."""
    t_now = datetime(2025, 6, 1, 9, 0, 0)
    utc_offset = t_now.astimezone().utcoffset()
    utcnow_notz = t_now - utc_offset

    # Case A: night = True (hits line 393: night_stop = today_meridian)
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = -1.0  # night

        t_prev_anti = utcnow_notz - timedelta(hours=9)
        t_today_meridian = utcnow_notz + timedelta(hours=3)
        t_next_meridian = utcnow_notz + timedelta(hours=27)
        t_next_anti = utcnow_notz + timedelta(hours=15)
        t_next_anti_2 = utcnow_notz + timedelta(hours=39)

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None

    # Case B: night = False (hits line 395: night_stop = next_meridian)
    with patch('ephem.Observer') as mock_obs_cls, patch('ephem.Sun') as mock_sun_cls, \
         patch('indi_allsky.utils.datetime') as mock_dt:
        mock_dt.now.return_value = t_now
        mock_dt.strptime = datetime.strptime

        mock_obs = MagicMock()
        mock_obs_cls.return_value = mock_obs
        mock_sun = MagicMock()
        mock_sun_cls.return_value = mock_sun
        mock_sun.alt = 0.5  # day

        mock_obs.previous_antitransit.return_value.datetime.return_value = t_prev_anti
        mock_obs.next_transit.return_value.datetime.side_effect = [t_today_meridian, t_next_meridian]
        mock_obs.next_antitransit.return_value.datetime.side_effect = [t_next_anti, t_next_anti_2]

        trans = date_calcs.getNextDayNightTransition()
        assert trans is not None

