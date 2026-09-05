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
    # Blue and red unchanged
    assert np.array_equal(res_night[:, :, 0], bgr_night[:, :, 0])
    assert np.array_equal(res_night[:, :, 2], bgr_night[:, :, 2])

    # Day mode (different midtones produces different green stretch)
    scnr.night_av[constants.NIGHT_NIGHT] = False
    bgr_day = np.full((50, 50, 3), 128, dtype=np.uint8)
    res_day = scnr.green_mtf(bgr_day)
    assert res_day.shape == (50, 50, 3)
    assert not np.array_equal(res_night[:, :, 1], res_day[:, :, 1])


def test_scnr_additive_mask():
    config = {'SCNR_AMOUNT': 0.5}
    scnr = IndiAllskyScnr(config, {constants.NIGHT_NIGHT: True})

    # Grayscale early return
    gray = np.full((20, 20), 100, dtype=np.uint8)
    assert np.array_equal(scnr.additive_mask(gray), gray)

    # Color BGR test: pure green pixel vs white pixel
    # Pure green: B=0, G=200, R=0 -> m=0 -> G reduced by 50% to 100
    # White: B=255, G=200, R=255 -> m=1.0 -> G preserved at 200
    img = np.zeros((1, 2, 3), dtype=np.uint8)
    img[0, 0] = [0, 200, 0]       # pure green
    img[0, 1] = [255, 200, 255]   # white

    res = scnr.additive_mask(img)
    assert res.shape == (1, 2, 3)
    # Pure green reduced: G becomes 100
    assert res[0, 0, 1] == 100
    assert res[0, 0, 0] == 0
    assert res[0, 0, 2] == 0
    # White preserved: G remains 200
    assert res[0, 1, 1] == 200
    assert res[0, 1, 0] == 255
    assert res[0, 1, 2] == 255
