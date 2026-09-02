from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pytest

from indi_allsky.asi676mc_calibration_engine import (
    is_recoverable_fits_error,
    _parse_timestamp,
    _header_float,
    RepairedFitsError,
    CALIBRATION_OPTIONS,
    DEFAULT_SETTINGS,
)


def test_calibration_options_constants():
    assert 'MIN_BAD_PAIRS' in CALIBRATION_OPTIONS
    assert 'SAMPLE_STEP' in CALIBRATION_OPTIONS
    assert CALIBRATION_OPTIONS['MIN_BAD_PAIRS'] == 7
    assert DEFAULT_SETTINGS is not None


def test_is_recoverable_fits_error():
    assert is_recoverable_fits_error(ValueError("bad data")) is True
    assert is_recoverable_fits_error(TypeError("type mismatch")) is True
    assert is_recoverable_fits_error(OSError("file missing")) is True
    assert is_recoverable_fits_error(RuntimeError("fatal")) is False


def test_parse_timestamp():
    header = {'DATE-OBS': '2026-09-01T12:00:00Z'}
    path = Path("image_20260901_120000.fits")
    ts = _parse_timestamp(header, path)
    assert ts > 0

    # Fallback to filename
    empty_header = {}
    ts_file = _parse_timestamp(empty_header, path)
    assert ts_file > 0


def test_header_float():
    header = {'EXPOSURE': '15.5', 'EXPTIME': '15.5'}
    val = _header_float(header, 'EXPOSURE', 'EXPTIME')
    assert val == 15.5

    missing_val = _header_float(header, 'NONEXISTENT', default=1.0)
    assert missing_val == 1.0
