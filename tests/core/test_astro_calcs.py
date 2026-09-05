import math
from datetime import datetime, timezone
from multiprocessing import Array
import ephem
import pytest

from indi_allsky.utils import IndiAllSkyDateCalcs
from indi_allsky import constants


def test_date_calcs_initialization():
    config = {
        'NIGHT_SUN_ALT_DEG': -6.0,
    }
    # position: [lat, lon, elev, ...]
    position_av = Array('d', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    
    date_calcs = IndiAllSkyDateCalcs(config, position_av)
    assert date_calcs.night_sun_radians == math.radians(-6.0)


def test_calc_day_date_output():
    config = {
        'NIGHT_SUN_ALT_DEG': -6.0,
    }
    # Adelaide, Australia (-34.9285, 138.6007)
    position_av = Array('d', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    date_calcs = IndiAllSkyDateCalcs(config, position_av)

    # calcDayDate expects local datetime (offset naive, as passed by capture/processing)
    now = datetime(2026, 8, 31, 12, 0, 0)
    day_date = date_calcs.calcDayDate(now)
    
    assert day_date is not None
    assert hasattr(day_date, 'year')
    assert hasattr(day_date, 'month')
    assert hasattr(day_date, 'day')


def test_calc_day_date_polar_regions():
    config = {
        'NIGHT_SUN_ALT_DEG': -6.0,
    }
    # High latitude (e.g. 75.0 N, -70.0 W)
    position_av = Array('d', [75.0, -70.0, 10.0, 0.0, 0.0])
    date_calcs = IndiAllSkyDateCalcs(config, position_av)

    # Summer solstice noon
    summer_dt = datetime(2024, 6, 21, 12, 0, 0)
    summer_date = date_calcs.calcDayDate(summer_dt)
    assert summer_date is not None
    assert summer_date.year == 2024

    # Winter solstice midnight
    winter_dt = datetime(2024, 12, 21, 0, 30, 0)
    winter_date = date_calcs.calcDayDate(winter_dt)
    assert winter_date is not None
    assert winter_date.year == 2024


def test_get_day_date_and_next_transition():
    config = {
        'NIGHT_SUN_ALT_DEG': -6.0,
    }
    position_av = Array('d', [51.5074, -0.1278, 25.0, 0.0, 0.0])  # London
    date_calcs = IndiAllSkyDateCalcs(config, position_av)

    current_date = date_calcs.getDayDate()
    assert current_date is not None

    next_transition = date_calcs.getNextDayNightTransition()
    assert next_transition is not None
    assert isinstance(next_transition, datetime)


def test_sun_moon_separation_and_ephem_calc():
    obs = ephem.Observer()
    obs.lat = math.radians(33.0)
    obs.lon = math.radians(-84.0)
    obs.elevation = 300
    obs.date = datetime(2024, 6, 21, 12, 0, 0)

    sun = ephem.Sun()
    moon = ephem.Moon()
    sun.compute(obs)
    moon.compute(obs)

    sep_rad = ephem.separation(sun, moon)
    sep_deg = math.degrees(sep_rad)
    assert 0.0 <= sep_deg <= 180.0

