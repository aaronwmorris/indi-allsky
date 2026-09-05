import ctypes
from multiprocessing import Array
from pathlib import Path
import numpy as np
from astropy.io import fits
import pytest

from indi_allsky.darks import (
    IndiAllSkyDarksProcessor,
    IndiAllSkyDarksAverage,
    IndiAllSkyDarksSigmaClip,
)


@pytest.fixture
def darks_processor_setup(tmp_path):
    config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'LOCATION_ELEVATION': 50,
        'IMAGE_FOLDER': str(tmp_path),
        'CCD_CONFIG': {
            'NIGHT': {'BINNING': 1},
            'DAY': {'BINNING': 1},
            'MOONMODE': {'BINNING': 1},
        },
    }
    exposure_av = Array(ctypes.c_int32, [1000000, 1000000, 0, 1000, 100, 30000000, 5000000])
    gain_av = Array(ctypes.c_int32, [100000, 100000, 0, 0, 100000, 100000, 400000, 50000, 200000, 100000])
    binning_av = Array('i', [1, 1, 1, 2, 1, 1])

    return config, exposure_av, gain_av, binning_av


def test_darks_processor_properties(darks_processor_setup):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    processor = IndiAllSkyDarksProcessor(config, exp_av, gain_av, bin_av)

    processor.bitmax = 12
    assert processor.bitmax == 12

    processor.hotpixel_adu_percent = 85
    assert processor.hotpixel_adu_percent == 85


def test_darks_average_stacking(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    stacker = IndiAllSkyDarksAverage(config, exp_av, gain_av, bin_av)
    assert str(stacker) == 'Average Stacking'

    # Create dummy FITS dark frames
    fit_dir = tmp_path / "fits"
    fit_dir.mkdir()

    d1 = np.full((32, 32), 100, dtype=np.uint16)
    d2 = np.full((32, 32), 120, dtype=np.uint16)
    fits.writeto(fit_dir / "dark1.fit", d1)
    fits.writeto(fit_dir / "dark2.fit", d2)

    out_file = tmp_path / "master_dark.fit"
    dark_avg, hot_count = stacker.stack(fit_dir, out_file, exposure=1.0, image_bitpix=16)

    assert out_file.exists()
    assert dark_avg == pytest.approx(110.0)

    # Read back stacked fits
    with fits.open(out_file) as hdul:
        assert hdul[0].data.shape == (32, 32)
        assert np.all(hdul[0].data == 110)


def test_bad_pixel_map_generation(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    processor = IndiAllSkyDarksProcessor(config, exp_av, gain_av, bin_av)
    processor.hotpixel_adu_percent = 50

    fit_dir = tmp_path / "fits_bpm"
    fit_dir.mkdir()

    frame = np.zeros((32, 32), dtype=np.uint16)
    frame[10, 10] = 60000  # Hot pixel above 50%
    frame[20, 20] = 50000  # Another hot pixel
    fits.writeto(fit_dir / "dark_bpm.fit", frame)

    out_bpm = tmp_path / "master_bpm.fit"
    bpm_avg, hot_count = processor.buildBadPixelMap(fit_dir, out_bpm, exposure=1.0, image_bitpix=16)

    assert out_bpm.exists()
    assert hot_count == 2
