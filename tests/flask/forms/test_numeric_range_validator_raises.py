"""Tests for numeric type-check raise conditions across validators."""
from collections import namedtuple
from unittest.mock import MagicMock

import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms as f_mod

Field = namedtuple('Field', ['data'])


def test_startrails_timelapse_minframes_non_int():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.STARTRAILS_TIMELAPSE_MINFRAMES_validator(form, Field('not_an_int'))


def test_lightgraph_rgb_channel_exceeds_255():
    form = MagicMock()
    with pytest.raises(ValidationError, match='Invalid syntax'):
        f_mod.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(form, Field('300,0,0'))


def test_rgb_color_channel_exceeds_255():
    form = MagicMock()
    with pytest.raises(ValidationError, match='Invalid syntax'):
        f_mod.RGB_COLOR_validator(form, Field('256,128,0'))


def test_as3935_noise_level_non_int():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.TEMP_SENSOR__AS3935_NOISE_LEVEL_validator(form, Field('bad'))


def test_as3935_spike_rejection_non_int():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator(form, Field('bad'))


def test_healthcheck_disk_usage_non_numeric():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.HEALTHCHECK__DISK_USAGE_validator(form, Field('high'))


def test_healthcheck_swap_usage_non_numeric():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.HEALTHCHECK__SWAP_USAGE_validator(form, Field('high'))


def test_adsb_alt_deg_min_non_numeric():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.ADSB__ALT_DEG_MIN_validator(form, Field('high'))


def test_adsb_label_limit_non_int():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.ADSB__LABEL_LIMIT_validator(form, Field('many'))


def test_satellite_alt_deg_min_non_numeric():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.SATELLITE_TRACK__ALT_DEG_MIN_validator(form, Field('high'))


def test_satellite_label_limit_non_int():
    form = MagicMock()
    with pytest.raises(ValidationError, match='valid number'):
        f_mod.SATELLITE_TRACK__LABEL_LIMIT_validator(form, Field('many'))
