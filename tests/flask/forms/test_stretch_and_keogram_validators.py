from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_web_and_stretch_validators(tmp_path):
    # WEB_EXTRA_TEXT_validator
    with pytest.raises(ValidationError, match='Invalid file name'):
        forms.WEB_EXTRA_TEXT_validator(None, DummyField('bad?name?'))

    with pytest.raises(ValidationError, match='File does not exist'):
        forms.WEB_EXTRA_TEXT_validator(None, DummyField(str(tmp_path / 'missing.txt')))

    dir_file = tmp_path / 'a_dir'
    dir_file.mkdir()
    with pytest.raises(ValidationError, match='Not a file'):
        forms.WEB_EXTRA_TEXT_validator(None, DummyField(str(dir_file)))

    # WEBSOCKET_API_KEY_validator
    forms.WEBSOCKET_API_KEY_validator(None, DummyField(''))
    forms.WEBSOCKET_API_KEY_validator(None, DummyField('valid_api-key_123'))
    with pytest.raises(ValidationError, match='API key can only contain'):
        forms.WEBSOCKET_API_KEY_validator(None, DummyField('invalid key with spaces!'))

    # IMAGE_STRETCH__CLASSNAME_validator
    forms.IMAGE_STRETCH__CLASSNAME_validator(None, DummyField(''))
    forms.IMAGE_STRETCH__CLASSNAME_validator(None, DummyField('stretch-class_1'))
    with pytest.raises(ValidationError, match='Invalid class syntax'):
        forms.IMAGE_STRETCH__CLASSNAME_validator(None, DummyField('invalid class!'))

    # IMAGE_STRETCH__MODE1_GAMMA_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE1_GAMMA_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Gamma must be 0 or greater'):
        forms.IMAGE_STRETCH__MODE1_GAMMA_validator(None, DummyField(-1.0))
    forms.IMAGE_STRETCH__MODE1_GAMMA_validator(None, DummyField(1.0))

    # IMAGE_STRETCH__MODE1_STDDEVS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE1_STDDEVS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Standard deviations must be 1.0 or greater'):
        forms.IMAGE_STRETCH__MODE1_STDDEVS_validator(None, DummyField(0.5))
    forms.IMAGE_STRETCH__MODE1_STDDEVS_validator(None, DummyField(2.0))

    # IMAGE_STRETCH__MODE2_SHADOWS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE2_SHADOWS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.0 or greater'):
        forms.IMAGE_STRETCH__MODE2_SHADOWS_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Value must be 0.5 or less'):
        forms.IMAGE_STRETCH__MODE2_SHADOWS_validator(None, DummyField(0.6))
    forms.IMAGE_STRETCH__MODE2_SHADOWS_validator(None, DummyField(0.2))

    # IMAGE_STRETCH__MODE2_MIDTONES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE2_MIDTONES_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.0 or greater'):
        forms.IMAGE_STRETCH__MODE2_MIDTONES_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.IMAGE_STRETCH__MODE2_MIDTONES_validator(None, DummyField(1.2))
    forms.IMAGE_STRETCH__MODE2_MIDTONES_validator(None, DummyField(0.5))

    # IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.5 or greater'):
        forms.IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator(None, DummyField(0.4))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator(None, DummyField(1.2))
    forms.IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator(None, DummyField(0.8))


def test_stretch_mode3_validators():
    # IMAGE_STRETCH__MODE3_BLACK_CLIP_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE3_BLACK_CLIP_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be -10.0 or greater'):
        forms.IMAGE_STRETCH__MODE3_BLACK_CLIP_validator(None, DummyField(-11.0))
    with pytest.raises(ValidationError, match='Value must be 0.0 or less'):
        forms.IMAGE_STRETCH__MODE3_BLACK_CLIP_validator(None, DummyField(0.5))
    forms.IMAGE_STRETCH__MODE3_BLACK_CLIP_validator(None, DummyField(-2.0))

    # IMAGE_STRETCH__MODE3_SHADOWS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE3_SHADOWS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.0 or greater'):
        forms.IMAGE_STRETCH__MODE3_SHADOWS_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Value must be 0.5 or less'):
        forms.IMAGE_STRETCH__MODE3_SHADOWS_validator(None, DummyField(0.6))
    forms.IMAGE_STRETCH__MODE3_SHADOWS_validator(None, DummyField(0.2))

    # IMAGE_STRETCH__MODE3_MIDTONES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE3_MIDTONES_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.0 or greater'):
        forms.IMAGE_STRETCH__MODE3_MIDTONES_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.IMAGE_STRETCH__MODE3_MIDTONES_validator(None, DummyField(1.2))
    forms.IMAGE_STRETCH__MODE3_MIDTONES_validator(None, DummyField(0.5))

    # IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.5 or greater'):
        forms.IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator(None, DummyField(0.4))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator(None, DummyField(1.2))
    forms.IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator(None, DummyField(0.8))


def test_rotate_and_keogram_validators():
    # IMAGE_ROTATE_ANGLE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_ROTATE_ANGLE_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Rotation angle must be -180 or greater'):
        forms.IMAGE_ROTATE_ANGLE_validator(None, DummyField(-185))
    with pytest.raises(ValidationError, match='Rotation angle must be 180 or less'):
        forms.IMAGE_ROTATE_ANGLE_validator(None, DummyField(185))
    forms.IMAGE_ROTATE_ANGLE_validator(None, DummyField(90))

    # KEOGRAM_ANGLE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.KEOGRAM_ANGLE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Rotation angle must be -180 or greater'):
        forms.KEOGRAM_ANGLE_validator(None, DummyField(-185.0))
    with pytest.raises(ValidationError, match='Rotation angle must be 180 or less'):
        forms.KEOGRAM_ANGLE_validator(None, DummyField(185.0))
    forms.KEOGRAM_ANGLE_validator(None, DummyField(45.0))

    # KEOGRAM_H_SCALE_validator
    with pytest.raises(ValidationError, match='Keogram Horizontal Scaling factor must be greater than 0'):
        forms.KEOGRAM_H_SCALE_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Keogram Horizontal Scaling factor must be 100 or less'):
        forms.KEOGRAM_H_SCALE_validator(None, DummyField(101))
    forms.KEOGRAM_H_SCALE_validator(None, DummyField(50))

    # KEOGRAM_V_SCALE_validator
    with pytest.raises(ValidationError, match='Keogram Verticle Scaling factor must be greater than 0'):
        forms.KEOGRAM_V_SCALE_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Keogram Verticle Scaling factor must be 100 or less'):
        forms.KEOGRAM_V_SCALE_validator(None, DummyField(101))
    forms.KEOGRAM_V_SCALE_validator(None, DummyField(50))

    # KEOGRAM_CROP_TOP_validator & KEOGRAM_CROP_BOTTOM_validator
    with pytest.raises(ValidationError, match='Keogram Crop percent must be 0 or greater'):
        forms.KEOGRAM_CROP_TOP_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Keogram crop percent must be 49 or less'):
        forms.KEOGRAM_CROP_TOP_validator(None, DummyField(50))
    forms.KEOGRAM_CROP_TOP_validator(None, DummyField(10))

    forms.KEOGRAM_CROP_BOTTOM_validator(None, DummyField(10))


def test_realtime_and_startrails_validators():
    # LONGTERM_KEOGRAM__OFFSET_X_validator & Y
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LONGTERM_KEOGRAM__OFFSET_X_validator(None, DummyField(10.5))
    forms.LONGTERM_KEOGRAM__OFFSET_X_validator(None, DummyField(10))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LONGTERM_KEOGRAM__OFFSET_Y_validator(None, DummyField(10.5))
    forms.LONGTERM_KEOGRAM__OFFSET_Y_validator(None, DummyField(10))

    # REALTIME_KEOGRAM__MAX_ENTRIES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.REALTIME_KEOGRAM__MAX_ENTRIES_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Entries must be 0 or greater'):
        forms.REALTIME_KEOGRAM__MAX_ENTRIES_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Entries must be 5000 or less'):
        forms.REALTIME_KEOGRAM__MAX_ENTRIES_validator(None, DummyField(10001))
    forms.REALTIME_KEOGRAM__MAX_ENTRIES_validator(None, DummyField(1000))

    # REALTIME_KEOGRAM__SAVE_INTERVAL_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.REALTIME_KEOGRAM__SAVE_INTERVAL_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Entries must be 1 or greater'):
        forms.REALTIME_KEOGRAM__SAVE_INTERVAL_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Entries must be 100 or less'):
        forms.REALTIME_KEOGRAM__SAVE_INTERVAL_validator(None, DummyField(101))
    forms.REALTIME_KEOGRAM__SAVE_INTERVAL_validator(None, DummyField(10))

    # STARTRAILS_MAX_ADU_validator
    with pytest.raises(ValidationError, match='Star Trails Max ADU must be greater than 0'):
        forms.STARTRAILS_MAX_ADU_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Star Trails Max ADU must be 255 or less'):
        forms.STARTRAILS_MAX_ADU_validator(None, DummyField(256))
    forms.STARTRAILS_MAX_ADU_validator(None, DummyField(200))

    # STARTRAILS_MASK_THOLD_validator
    with pytest.raises(ValidationError, match='Star Trails Mask Threshold must be greater than 0'):
        forms.STARTRAILS_MASK_THOLD_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Star Trails Mask Threshold must be 255 or less'):
        forms.STARTRAILS_MASK_THOLD_validator(None, DummyField(256))
    forms.STARTRAILS_MASK_THOLD_validator(None, DummyField(50))

    # STARTRAILS_PIXEL_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.STARTRAILS_PIXEL_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Star Trails Pixel Threshold must be 0 or greater'):
        forms.STARTRAILS_PIXEL_THOLD_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Star Trails Pixel Threshold must be 100 or less'):
        forms.STARTRAILS_PIXEL_THOLD_validator(None, DummyField(101))
    forms.STARTRAILS_PIXEL_THOLD_validator(None, DummyField(10))

    # STARTRAILS_MIN_STARS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.STARTRAILS_MIN_STARS_validator(None, DummyField(5.5))
    with pytest.raises(ValidationError, match='Minimum stars must be greater than 0'):
        forms.STARTRAILS_MIN_STARS_validator(None, DummyField(-1))
    forms.STARTRAILS_MIN_STARS_validator(None, DummyField(50))

    # STARTRAILS_SUN_ALT_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.STARTRAILS_SUN_ALT_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sun altitude must be greater than -90'):
        forms.STARTRAILS_SUN_ALT_THOLD_validator(None, DummyField(-91.0))
    with pytest.raises(ValidationError, match='Sun altitude must be less than 90'):
        forms.STARTRAILS_SUN_ALT_THOLD_validator(None, DummyField(91.0))
    forms.STARTRAILS_SUN_ALT_THOLD_validator(None, DummyField(-6.0))

    # STARTRAILS_MOON_ALT_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.STARTRAILS_MOON_ALT_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Moon altitude must be greater than -90'):
        forms.STARTRAILS_MOON_ALT_THOLD_validator(None, DummyField(-91.0))
    with pytest.raises(ValidationError, match='Moon altitude must be less than 91'):
        forms.STARTRAILS_MOON_ALT_THOLD_validator(None, DummyField(92.0))
    forms.STARTRAILS_MOON_ALT_THOLD_validator(None, DummyField(10.0))

    # STARTRAILS_MOON_PHASE_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.STARTRAILS_MOON_PHASE_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Moon phase must be greater than 0'):
        forms.STARTRAILS_MOON_PHASE_THOLD_validator(None, DummyField(-1.0))
    with pytest.raises(ValidationError, match='Moon phase must be less than 101'):
        forms.STARTRAILS_MOON_PHASE_THOLD_validator(None, DummyField(102.0))
    forms.STARTRAILS_MOON_PHASE_THOLD_validator(None, DummyField(50.0))


def test_queue_validators():
    # IMAGE_QUEUE_MAX_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_QUEUE_MAX_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Queue max size must be 2 or greater'):
        forms.IMAGE_QUEUE_MAX_validator(None, DummyField(1))
    forms.IMAGE_QUEUE_MAX_validator(None, DummyField(10))

    # IMAGE_QUEUE_MIN_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_QUEUE_MIN_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Queue min size must be 1 or greater'):
        forms.IMAGE_QUEUE_MIN_validator(None, DummyField(0))
    forms.IMAGE_QUEUE_MIN_validator(None, DummyField(5))

    # IMAGE_QUEUE_BACKOFF_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_QUEUE_BACKOFF_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Backoff multiplier must be greater than 0'):
        forms.IMAGE_QUEUE_BACKOFF_validator(None, DummyField(0.0))
    forms.IMAGE_QUEUE_BACKOFF_validator(None, DummyField(1.5))
