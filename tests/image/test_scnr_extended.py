import numpy as np
import pytest

from indi_allsky.scnr import IndiAllskyScnr
from indi_allsky import constants


def test_scnr_green_mtf_branches():
    # Test with USE_NIGHT_COLOR True and False
    config = {
        'USE_NIGHT_COLOR': False,
        'SCNR_MTF_MIDTONES': 0.55,
        'SCNR_MTF_MIDTONES_DAY': 0.65,
    }
    night_av = {constants.NIGHT_NIGHT: True}
    scnr = IndiAllskyScnr(config, night_av)

    # Night mode
    bgr_night = np.full((50, 50, 3), 128, dtype=np.uint8)
    res_night = scnr.green_mtf(bgr_night)
    assert res_night.shape == (50, 50, 3)

    # Day mode
    scnr.night_av[constants.NIGHT_NIGHT] = False
    bgr_day = np.full((50, 50, 3), 128, dtype=np.uint8)
    res_day = scnr.green_mtf(bgr_day)
    assert res_day.shape == (50, 50, 3)


def test_scnr_additive_mask():
    config = {'SCNR_AMOUNT': 0.5}
    scnr = IndiAllskyScnr(config, {constants.NIGHT_NIGHT: True})

    # Grayscale
    gray = np.full((20, 20), 100, dtype=np.uint8)
    assert np.array_equal(scnr.additive_mask(gray), gray)
