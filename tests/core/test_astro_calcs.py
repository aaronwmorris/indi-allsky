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
