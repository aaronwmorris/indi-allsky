import ctypes
from multiprocessing import Array
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
from astropy.io import fits
import pytest

from indi_allsky.darks import (
    IndiAllSkyDarks,
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
        'IMAGE_DIR': str(tmp_path / 'images'),
        'VARLIB_FOLDER': str(tmp_path / 'varlib'),
        'CCD_CONFIG': {
            'NIGHT': {'BINNING': 1},
            'DAY': {'BINNING': 1},
            'MOONMODE': {'BINNING': 1},
        },
    }
    Path(config['IMAGE_DIR']).mkdir(parents=True, exist_ok=True)
    Path(config['VARLIB_FOLDER']).mkdir(parents=True, exist_ok=True)

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
    assert repr(stacker) == 'Average Stacking'

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


def test_darks_sigma_clip_stacking(darks_processor_setup, tmp_path):
    config, exp_av, gain_av, bin_av = darks_processor_setup
    stacker = IndiAllSkyDarksSigmaClip(config, exp_av, gain_av, bin_av)
    assert str(stacker) == 'Sigma Clipping'
    assert repr(stacker) == 'Sigma Clipping'

    fit_dir = tmp_path / "fits_sc"
    fit_dir.mkdir()

    d1 = np.full((32, 32), 100, dtype=np.uint16)
    d2 = np.full((32, 32), 105, dtype=np.uint16)
    d3 = np.full((32, 32), 102, dtype=np.uint16)

    for idx, d in enumerate([d1, d2, d3], 1):
        hdu = fits.PrimaryHDU(d)
        hdu.header['BUNIT'] = 'adu'
        hdu.header['EXPTIME'] = 1.0
        hdu.writeto(fit_dir / f"dark{idx}.fit")

    out_file = tmp_path / "master_dark_sc.fit"
    dark_avg, hot_count = stacker.stack(fit_dir, out_file, exposure=1.0, image_bitpix=16)

    assert out_file.exists()
    assert dark_avg >= 90


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


def test_darks_time_formatting_and_runtime_estimation(app):
    with app.app_context():
        # Format time static method
        formatted = IndiAllSkyDarks._format_time(3665)
        assert formatted == "01h:01m:05s"

        with patch.object(IndiAllSkyDarks, '__init__', return_value=None):
            darks = IndiAllSkyDarks()
            darks.count = 3
            runtime = darks._estimate_runtime(
                remaining_exposures=[1.0, 2.0],
                remaining_configs=2,
                overhead_per_exposure=0.5,
            )
            # (sum([1,2])*3 + 2*0.5) * 2 = (9 + 1) * 2 = 20
            assert runtime == 20.0


def test_darks_check_available_space(app, base_config):
    with app.app_context():
        with patch.object(IndiAllSkyDarks, '__init__', return_value=None):
            darks = IndiAllSkyDarks()
            darks.config = base_config
            darks.checkAvailableSpace()

