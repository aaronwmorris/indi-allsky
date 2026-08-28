import cv2
import numpy
import sys
import types

from indi_allsky import constants
from indi_allsky import protection_masks
from indi_allsky.denoise import IndiAllskyDenoise


def _denoiser(config, is_night=False):
    night_av = [False] * (constants.NIGHT_NIGHT + 1)
    night_av[constants.NIGHT_NIGHT] = is_night
    return IndiAllskyDenoise(config, night_av)


def test_bilateral_uses_day_settings_when_day_color_is_enabled():
    denoiser = _denoiser({
        'USE_NIGHT_COLOR': False,
        'BILATERAL_SIGMA_COLOR': 11,
        'BILATERAL_SIGMA_SPACE': 12,
        'BILATERAL_SIGMA_COLOR_DAY': 21,
        'BILATERAL_SIGMA_SPACE_DAY': 22,
    })

    assert denoiser._get_bilateral_sigma() == (21, 22)


def test_bilateral_uses_night_settings_at_night():
    denoiser = _denoiser({
        'USE_NIGHT_COLOR': False,
        'BILATERAL_SIGMA_COLOR': 11,
        'BILATERAL_SIGMA_SPACE': 12,
        'BILATERAL_SIGMA_COLOR_DAY': 21,
        'BILATERAL_SIGMA_SPACE_DAY': 22,
    }, is_night=True)

    assert denoiser._get_bilateral_sigma() == (11, 12)


def test_wavelet_blend_is_limited_by_configured_maximum(monkeypatch):
    denoiser = _denoiser({
        'IMAGE_DENOISE_STRENGTH': 5,
        'WAVELET_MAX_BLEND': 0.25,
    })
    captured = {}

    def finalize(original, processed, blend, dtype_max):
        captured['blend'] = blend
        return processed

    monkeypatch.setattr(denoiser, '_finalize_denoise', finalize)
    denoiser.wavelet(numpy.arange(256, dtype=numpy.uint8).reshape(16, 16))

    assert captured['blend'] == 0.25


def test_high_bit_depth_median_preserves_native_values():
    denoiser = _denoiser({'CCD_BIT_DEPTH': 12})
    image = numpy.array([
        [101, 203, 307, 401, 509],
        [601, 701, 809, 907, 1009],
        [1103, 1201, 12345, 1301, 1409],
        [1501, 1601, 1709, 1801, 1901],
        [2003, 2101, 2203, 2309, 2401],
    ], dtype=numpy.uint16)

    result = denoiser._medianBlur(image, 5)

    assert result.dtype == numpy.uint16
    assert numpy.array_equal(result, cv2.medianBlur(image, 5))
    assert result[2, 2] % 257 != 0


def test_star_percentile_increases_full_mask_detection_threshold(monkeypatch):
    captured = {}

    class FakeDAOStarFinder:
        def __init__(self, fwhm, threshold):
            captured['threshold'] = threshold

        def __call__(self, data):
            return None

    monkeypatch.setattr(protection_masks, '_estimate_background_stats',
                        lambda data: (10.0, 2.0))
    monkeypatch.setitem(sys.modules, 'photutils.detection',
                        types.SimpleNamespace(DAOStarFinder=FakeDAOStarFinder))
    data = numpy.array([[10.0, 10.0, 10.0], [10.0, 10.0, 110.0]], dtype=numpy.float32)

    protection_masks._generate_star_mask(data, percentile=90.0,
                                         threshold_sigma=2.0, fwhm=5.0,
                                         expand_radius=0)

    assert captured['threshold'] == numpy.percentile(data, 90.0) - 10.0