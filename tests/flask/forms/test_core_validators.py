"""Comprehensive tests for all remaining validator functions in indi_allsky.flask.forms."""
import io
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import cv2
import numpy as np
from wtforms.validators import ValidationError

from indi_allsky.flask import forms
from indi_allsky.flask.forms import IndiAllskyConfigForm


class DummyField:
    def __init__(self, data):
        self.data = data


@pytest.fixture
def config_form(flask_app, base_config):
    with flask_app.test_request_context():
        data = dict(base_config)
        for slot in ['A', 'B', 'C', 'D', 'E', 'F']:
            data[f'TEMP_SENSOR__{slot}_CLASSNAME'] = 'None'
            data[f'TEMP_SENSOR__{slot}_LABEL'] = f'Sensor {slot}'
            data[f'TEMP_SENSOR__{slot}_USER_VAR_SLOT'] = 'None'
            data[f'TEMP_SENSOR__{slot}_PIN_1'] = 'None'
        f = IndiAllskyConfigForm(data=data)
        return f


# ==============================================================================
# Choice & Enum Validators
# ==============================================================================

def test_choice_and_enum_validators(config_form):
    """Test validators that validate against choices on form."""
    choice_validators = [
        (forms.CCD_CONFIG__EXPOSURE_CLASSNAME_validator, 'invalid_choice'),
        (forms.CCD_CONFIG__AUTO_GAIN_LEVELS_validator, 99999),
        (forms.TIMELAPSE__PRE_PROCESSOR_validator, 'invalid_pre_proc'),
        (forms.CFA_PATTERN_validator, 'INVALID_CFA'),
        (forms.IMAGE_COLORMAP_validator, 'INVALID_COLORMAP'),
        (forms.SCNR_ALGORITHM_validator, 'INVALID_SCNR'),
        (forms.IMAGE_DENOISE_validator, 'INVALID_DENOISE'),
        (forms.TEMP_DISPLAY_validator, 'INVALID_TEMP_DISP'),
        (forms.PRESSURE_DISPLAY_validator, 'INVALID_PRESS_DISP'),
        (forms.WINDSPEED_DISPLAY_validator, 'INVALID_WIND_DISP'),
        (forms.IMAGE_FILE_TYPE_validator, 'invalid_ext'),
        (forms.IMAGE_SAVE_FITS_PERIOD_validator, 'invalid_fits_period'),
        (forms.FILETRANSFER__CLASSNAME_validator, 'INVALID_CLASS'),
        (forms.S3UPLOAD__CLASSNAME_validator, 'INVALID_S3_CLASS'),
        (forms.S3UPLOAD__ACL_validator, 'INVALID_S3_ACL'),
        (forms.S3UPLOAD__STORAGE_CLASS_validator, 'INVALID_STORAGE_CLASS'),
        (forms.YOUTUBE__PRIVACY_STATUS_validator, 'INVALID_PRIVACY'),
        (forms.YOUTUBE__CATEGORY_validator, 'INVALID_CAT'),
        (forms.MQTTPUBLISH__PROTOCOL_validator, 'INVALID_MQTT_PROTO'),
        (forms.MQTTPUBLISH__TRANSPORT_validator, 'INVALID_MQTT_TRANS'),
        (forms.DEW_HEATER__CLASSNAME_validator, 'INVALID_DEW_CLASS'),
        (forms.FAN__CLASSNAME_validator, 'INVALID_FAN_CLASS'),
        (forms.GENERIC_GPIO__CLASSNAME_validator, 'INVALID_GPIO'),
        (forms.MANUAL_GPIO__CLASSNAME_validator, 'INVALID_MANUAL_GPIO'),
        (forms.TEMP_SENSOR__CLASSNAME_validator, 'INVALID_SENSOR_CLASS'),
        (forms.SENSOR_USER_VAR_SLOT_validator, 'INVALID_USER_VAR_SLOT'),
        (forms.TEMP_SENSOR__SHT4X_MODE_validator, 'INVALID_SHT_MODE'),
        (forms.TEMP_SENSOR__HDC302X_HEATER_validator, 'INVALID_HDC_HEATER'),
        (forms.TEMP_SENSOR__SI7021_HEATER_LEVEL_validator, 'INVALID_HEATER_LVL'),
        (forms.TEMP_SENSOR__TSL2591_GAIN_validator, 'INVALID_GAIN'),
        (forms.TEMP_SENSOR__TSL2591_INT_validator, 'INVALID_INT'),
        (forms.TEMP_SENSOR__VEML7700_GAIN_validator, 'INVALID_GAIN'),
        (forms.TEMP_SENSOR__VEML7700_INT_validator, 'INVALID_INT'),
        (forms.TEMP_SENSOR__SI1145_GAIN_validator, 'INVALID_GAIN'),
        (forms.TEMP_SENSOR__LTR390_GAIN_validator, 'INVALID_GAIN'),
    ]

    for val_func, bad_val in choice_validators:
        with pytest.raises(ValidationError):
            val_func(config_form, DummyField(bad_val))


def test_sensor_and_chart_slot_validators(config_form):
    """Test SENSOR_SLOT_validator and CUSTOM_CHART_validator."""
    with pytest.raises(ValidationError):
        forms.SENSOR_SLOT_validator(config_form, DummyField('nonexistent_slot'))

    with pytest.raises(ValidationError):
        forms.CUSTOM_CHART_validator(config_form, DummyField('nonexistent_chart_slot'))


def test_tsl2561_validators(config_form):
    """Test TEMP_SENSOR__TSL2561_GAIN_validator and INT validator."""
    forms.TEMP_SENSOR__TSL2561_GAIN_validator(config_form, DummyField(0))
    forms.TEMP_SENSOR__TSL2561_GAIN_validator(config_form, DummyField(1))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_GAIN_validator(config_form, DummyField(-1))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_GAIN_validator(config_form, DummyField(2))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_GAIN_validator(config_form, DummyField('invalid'))

    forms.TEMP_SENSOR__TSL2561_INT_validator(config_form, DummyField(0))
    forms.TEMP_SENSOR__TSL2561_INT_validator(config_form, DummyField(2))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_INT_validator(config_form, DummyField(-1))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_INT_validator(config_form, DummyField(3))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TSL2561_INT_validator(config_form, DummyField('invalid'))


def test_i2c_address_validator(config_form):
    """Test I2C_ADDRESS_validator."""
    forms.I2C_ADDRESS_validator(config_form, DummyField('0x77'))
    with pytest.raises(ValidationError):
        forms.I2C_ADDRESS_validator(config_form, DummyField('not_hex'))
    with pytest.raises(ValidationError):
        forms.I2C_ADDRESS_validator(config_form, DummyField('0x80'))  # > 127
    with pytest.raises(ValidationError):
        forms.I2C_ADDRESS_validator(config_form, DummyField('-0x05'))  # < 0


def test_device_pin_name_validator(config_form):
    """Test DEVICE_PIN_NAME_validator."""
    forms.DEVICE_PIN_NAME_validator(config_form, DummyField(''))
    forms.DEVICE_PIN_NAME_validator(config_form, DummyField('D1_pin'))
    with pytest.raises(ValidationError):
        forms.DEVICE_PIN_NAME_validator(config_form, DummyField('pin with space!@#'))


def test_image_rotate_validator(config_form):
    """Test IMAGE_ROTATE_validator."""
    forms.IMAGE_ROTATE_validator(config_form, DummyField('ROTATE_90_CLOCKWISE'))
    with pytest.raises(ValidationError):
        forms.IMAGE_ROTATE_validator(config_form, DummyField('INVALID_ROTATION_OPTION'))
    # cv2 missing attribute test
    with patch.object(cv2, 'ROTATE_90_CLOCKWISE', create=True):
        pass


def test_template_formatting_validators(config_form):
    """Test template validators that format test data."""
    # IMAGE_LABEL_TEMPLATE_validator
    forms.IMAGE_LABEL_TEMPLATE_validator(config_form, DummyField('{owner} {location} {exposure:.1f}'))
    with pytest.raises(ValidationError):
        forms.IMAGE_LABEL_TEMPLATE_validator(config_form, DummyField('{unknown_key_xyz}'))
    with pytest.raises(ValidationError):
        forms.IMAGE_LABEL_TEMPLATE_validator(config_form, DummyField('{owner:'))  # ValueError

    # WEB_STATUS_TEMPLATE_validator
    forms.WEB_STATUS_TEMPLATE_validator(config_form, DummyField('{status} {latitude:.2f}'))
    with pytest.raises(ValidationError):
        forms.WEB_STATUS_TEMPLATE_validator(config_form, DummyField('{unknown_status_key}'))
    with pytest.raises(ValidationError):
        forms.WEB_STATUS_TEMPLATE_validator(config_form, DummyField('{status:'))  # ValueError

    # TEMP_SENSOR__TITLE_TEMPLATE_validator
    forms.TEMP_SENSOR__TITLE_TEMPLATE_validator(config_form, DummyField('{name} {label} {probe}'))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TITLE_TEMPLATE_validator(config_form, DummyField('{unknown_ts_key}'))
    with pytest.raises(ValidationError):
        forms.TEMP_SENSOR__TITLE_TEMPLATE_validator(config_form, DummyField('{probe:'))

    # LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator
    forms.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(config_form, DummyField('{month:%B %Y}'))
    with pytest.raises(ValidationError):
        forms.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(config_form, DummyField('{unknown_month}'))
    with pytest.raises(ValidationError):
        forms.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(config_form, DummyField('{month:'))

    # S3UPLOAD__URL_TEMPLATE_validator
    forms.S3UPLOAD__URL_TEMPLATE_validator(config_form, DummyField('https://{host}/{bucket}/{namespace}'))
    with pytest.raises(ValidationError, match='Invalid URL template'):
        forms.S3UPLOAD__URL_TEMPLATE_validator(config_form, DummyField('bad url template?@'))
    with pytest.raises(ValidationError, match='end with a slash'):
        forms.S3UPLOAD__URL_TEMPLATE_validator(config_form, DummyField('https://{host}/{bucket}/'))
    with pytest.raises(ValidationError):
        forms.S3UPLOAD__URL_TEMPLATE_validator(config_form, DummyField('https://{bad_host_key}'))
    with pytest.raises(ValidationError):
        forms.S3UPLOAD__URL_TEMPLATE_validator(config_form, DummyField('https://{host:'))

    # YOUTUBE__TITLE_TEMPLATE_validator
    forms.YOUTUBE__TITLE_TEMPLATE_validator(config_form, DummyField('{day_date} {timeofday}'))
    with pytest.raises(ValidationError):
        forms.YOUTUBE__TITLE_TEMPLATE_validator(config_form, DummyField('{bad_key}'))
    with pytest.raises(ValidationError):
        forms.YOUTUBE__TITLE_TEMPLATE_validator(config_form, DummyField('{day_date:'))

    # YOUTUBE__DESCRIPTION_TEMPLATE_validator
    forms.YOUTUBE__DESCRIPTION_TEMPLATE_validator(config_form, DummyField(''))
    forms.YOUTUBE__DESCRIPTION_TEMPLATE_validator(config_form, DummyField('{day_date} {timeofday}'))
    with pytest.raises(ValidationError):
        forms.YOUTUBE__DESCRIPTION_TEMPLATE_validator(config_form, DummyField('{bad_key}'))
    with pytest.raises(ValidationError):
        forms.YOUTUBE__DESCRIPTION_TEMPLATE_validator(config_form, DummyField('{day_date:'))

    # ADSB validators
    forms.ADSB__IMAGE_LABEL_TEMPLATE_PREFIX_validator(config_form, DummyField('test'))
    forms.ADSB__AIRCRAFT_LABEL_TEMPLATE_validator(config_form, DummyField('{flight} {altitude:.0f}'))
    with pytest.raises(ValidationError):
        forms.ADSB__AIRCRAFT_LABEL_TEMPLATE_validator(config_form, DummyField('{bad_key}'))
    with pytest.raises(ValidationError):
        forms.ADSB__AIRCRAFT_LABEL_TEMPLATE_validator(config_form, DummyField('{flight:'))

    # Satellite Track validators
    forms.SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX_validator(config_form, DummyField('test'))
    forms.SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator(config_form, DummyField('{title} {alt:.1f}'))
    with pytest.raises(ValidationError):
        forms.SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator(config_form, DummyField('{bad_key}'))
    with pytest.raises(ValidationError):
        forms.SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator(config_form, DummyField('{title:'))


def test_asi676mc_highlight_blend_end_ratio_validator():
    """Test IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator."""
    mock_form = MagicMock()
    mock_form.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO.data = 0.5

    # valid: end ratio > start ratio
    forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator(mock_form, DummyField(0.8))

    # end ratio <= start ratio
    with pytest.raises(ValidationError):
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator(mock_form, DummyField(0.5))


def test_timelapse_and_startrail_ranges(config_form):
    """Test numerical bounds on timelapse, startrail, etc."""
    # TIMELAPSE_SKIP_FRAMES
    forms.TIMELAPSE_SKIP_FRAMES_validator(config_form, DummyField(5))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE_SKIP_FRAMES_validator(config_form, DummyField(11))

    # FFMPEG_BITRATE_validator
    forms.FFMPEG_BITRATE_validator(config_form, DummyField('5000k'))
    with pytest.raises(ValidationError):
        forms.FFMPEG_BITRATE_validator(config_form, DummyField('bad_bitrate'))

    # TIMELAPSE__IMAGE_CIRCLE
    forms.TIMELAPSE__IMAGE_CIRCLE_validator(config_form, DummyField(1000))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE__IMAGE_CIRCLE_validator(config_form, DummyField(50))

    # TIMELAPSE__KEOGRAM_RATIO
    forms.TIMELAPSE__KEOGRAM_RATIO_validator(config_form, DummyField(0.15))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE__KEOGRAM_RATIO_validator(config_form, DummyField(0.001))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE__KEOGRAM_RATIO_validator(config_form, DummyField(0.5))

    # TIMELAPSE__PRE_SCALE
    forms.TIMELAPSE__PRE_SCALE_validator(config_form, DummyField(50))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE__PRE_SCALE_validator(config_form, DummyField(0))

    # STARTRAILS_TIMELAPSE_MINFRAMES
    forms.STARTRAILS_TIMELAPSE_MINFRAMES_validator(config_form, DummyField(30))
    with pytest.raises(ValidationError):
        forms.STARTRAILS_TIMELAPSE_MINFRAMES_validator(config_form, DummyField(10))

    # TIMELAPSE_EXPIRE_DAYS
    forms.TIMELAPSE_EXPIRE_DAYS_validator(config_form, DummyField(7))
    with pytest.raises(ValidationError):
        forms.TIMELAPSE_EXPIRE_DAYS_validator(config_form, DummyField(0))

    # S3UPLOAD__ENDPOINT_URL
    forms.S3UPLOAD__ENDPOINT_URL_validator(config_form, DummyField(''))
    forms.S3UPLOAD__ENDPOINT_URL_validator(config_form, DummyField('https://s3.amazonaws.com'))
    with pytest.raises(ValidationError):
        forms.S3UPLOAD__ENDPOINT_URL_validator(config_form, DummyField('not_a_url_no_scheme'))


# ==============================================================================
# Filesystem & Script Validators
# ==============================================================================

def test_web_extra_text_and_image_extra_text(tmp_path):
    """Test WEB_EXTRA_TEXT_validator and IMAGE_EXTRA_TEXT_validator size and permission checks."""
    # WEB_EXTRA_TEXT_validator
    forms.WEB_EXTRA_TEXT_validator(None, DummyField(''))
    valid_file = tmp_path / 'extra.txt'
    valid_file.write_text('Hello World', encoding='utf-8')
    forms.WEB_EXTRA_TEXT_validator(None, DummyField(str(valid_file)))

    large_file = tmp_path / 'large.txt'
    large_file.write_bytes(b'A' * 10005)
    with pytest.raises(ValidationError, match='File is too large'):
        forms.WEB_EXTRA_TEXT_validator(None, DummyField(str(large_file)))

    with patch.object(Path, 'is_file', return_value=True), \
         patch('io.open', side_effect=PermissionError('denied')):
        with pytest.raises(ValidationError):
            forms.WEB_EXTRA_TEXT_validator(None, DummyField(str(valid_file)))

    # IMAGE_EXTRA_TEXT_validator
    forms.IMAGE_EXTRA_TEXT_validator(None, DummyField(''))
    forms.IMAGE_EXTRA_TEXT_validator(None, DummyField(str(valid_file)))
    with pytest.raises(ValidationError, match='File is too large'):
        forms.IMAGE_EXTRA_TEXT_validator(None, DummyField(str(large_file)))
    with patch.object(Path, 'is_file', return_value=True), \
         patch('io.open', side_effect=PermissionError('denied')):
        with pytest.raises(ValidationError):
            forms.IMAGE_EXTRA_TEXT_validator(None, DummyField(str(valid_file)))


def test_script_validator(tmp_path):
    """Test SCRIPT_validator."""
    forms.SCRIPT_validator(None, DummyField(''))

    # non-existent
    with pytest.raises(ValidationError, match='Script does not exist'):
        forms.SCRIPT_validator(None, DummyField(str(tmp_path / 'missing.sh')))

    # directory
    with pytest.raises(ValidationError, match='Script is not a file'):
        forms.SCRIPT_validator(None, DummyField(str(tmp_path)))

    # empty
    empty_f = tmp_path / 'empty.sh'
    empty_f.write_text('')
    with pytest.raises(ValidationError, match='Script is empty'):
        forms.SCRIPT_validator(None, DummyField(str(empty_f)))

    # not executable
    non_exec = tmp_path / 'nonexec.sh'
    non_exec.write_text('#!/bin/sh\necho ok\n')
    non_exec.chmod(0o644)
    with pytest.raises(ValidationError, match='Script is not executable'):
        forms.SCRIPT_validator(None, DummyField(str(non_exec)))

    # executable
    non_exec.chmod(0o755)
    forms.SCRIPT_validator(None, DummyField(str(non_exec)))


def test_ccd_temp_script_validator(tmp_path):
    """Test CCD_TEMP_SCRIPT_validator through all branches."""
    forms.CCD_TEMP_SCRIPT_validator(None, DummyField(''))

    # 1. Non-existent
    with pytest.raises(ValidationError, match='Temperature script does not exist'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(tmp_path / 'nonexistent.sh')))

    # 2. Directory
    with pytest.raises(ValidationError, match='Temperature script is not a file'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(tmp_path)))

    # 3. Empty
    empty_script = tmp_path / 'empty_script.sh'
    empty_script.write_text('')
    with pytest.raises(ValidationError, match='Temperature script is empty'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(empty_script)))

    # 4. Not executable
    empty_script.write_text('#!/bin/sh\n')
    empty_script.chmod(0o644)
    with pytest.raises(ValidationError, match='Temperature script is not executable'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(empty_script)))

    # 5. Successful script outputting valid JSON
    valid_script = tmp_path / 'valid_temp.sh'
    valid_script.write_text('#!/bin/sh\necho \'{"temp": 21.5}\' > "$TEMP_JSON"\nexit 0\n')
    valid_script.chmod(0o755)
    forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(valid_script)))

    # 6. Script exiting non-zero
    fail_script = tmp_path / 'fail_temp.sh'
    fail_script.write_text('#!/bin/sh\nexit 1\n')
    fail_script.chmod(0o755)
    with pytest.raises(ValidationError, match='exited abnormally'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(fail_script)))

    # 7. Script returning invalid JSON
    bad_json_script = tmp_path / 'bad_json_temp.sh'
    bad_json_script.write_text('#!/bin/sh\necho \'not json\' > "$TEMP_JSON"\nexit 0\n')
    bad_json_script.chmod(0o755)
    with pytest.raises(ValidationError):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(bad_json_script)))

    # 8. Script returning non-numerical temp
    non_num_script = tmp_path / 'non_num_temp.sh'
    non_num_script.write_text('#!/bin/sh\necho \'{"temp": "hot"}\' > "$TEMP_JSON"\nexit 0\n')
    non_num_script.chmod(0o755)
    with pytest.raises(ValidationError, match='non-numerical'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(non_num_script)))

    # 9. Script returning missing temp key
    missing_key_script = tmp_path / 'missing_key_temp.sh'
    missing_key_script.write_text('#!/bin/sh\necho \'{"humidity": 50}\' > "$TEMP_JSON"\nexit 0\n')
    missing_key_script.chmod(0o755)
    with pytest.raises(ValidationError, match='incorrect data'):
        forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(missing_key_script)))


def test_folder_validators_deep(tmp_path):
    """Test VARLIB_FOLDER, IMAGE_FOLDER, and IMAGE_EXPORT_FOLDER error paths."""
    # VARLIB_FOLDER exists but is file
    varlib_file = tmp_path / 'varlib_file'
    varlib_file.write_text('content')
    with pytest.raises(ValidationError, match='Path is not a directory'):
        forms.VARLIB_FOLDER_validator(None, DummyField(str(varlib_file)))

    # VARLIB_FOLDER permission errors
    with patch('os.access', return_value=False):
        with pytest.raises(ValidationError):
            forms.VARLIB_FOLDER_validator(None, DummyField(str(tmp_path)))

    # IMAGE_FOLDER disallowed chars and mkdir
    with pytest.raises(ValidationError, match='disallowed characters'):
        forms.IMAGE_FOLDER_validator(None, DummyField('/tmp/bad$folder'))

    new_img_dir = tmp_path / 'new_images_dir'
    forms.IMAGE_FOLDER_validator(None, DummyField(str(new_img_dir)))
    assert new_img_dir.is_dir()

    # IMAGE_EXPORT_FOLDER disallowed chars and mkdir
    with pytest.raises(ValidationError, match='disallowed characters'):
        forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField('/tmp/bad$export'))

    new_export_dir = tmp_path / 'new_export_dir'
    forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField(str(new_export_dir)))
    assert new_export_dir.is_dir()


def test_detect_mask_and_logo_overlay_validators(tmp_path):
    """Test DETECT_MASK_validator and LOGO_OVERLAY_validator."""
    # DETECT_MASK_validator
    forms.DETECT_MASK_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid file name'):
        forms.DETECT_MASK_validator(None, DummyField(str(tmp_path / 'mask?.png')))

    with pytest.raises(ValidationError, match='Mask file must be a PNG'):
        forms.DETECT_MASK_validator(None, DummyField(str(tmp_path / 'mask.jpg')))

    with pytest.raises(ValidationError, match='File does not exist'):
        forms.DETECT_MASK_validator(None, DummyField(str(tmp_path / 'missing.png')))

    # Directory ending in .png -> Not a file
    dir_png = tmp_path / 'dir.png'
    dir_png.mkdir()
    with pytest.raises(ValidationError, match='Not a file'):
        forms.DETECT_MASK_validator(None, DummyField(str(dir_png)))

    # PermissionError
    perm_file = tmp_path / 'perm.png'
    perm_file.write_bytes(b'png_content')
    with patch('io.open', side_effect=PermissionError('Access denied')):
        with pytest.raises(ValidationError, match='Access denied'):
            forms.DETECT_MASK_validator(None, DummyField(str(perm_file)))

    # Invalid image (corrupted / empty)
    corrupt_file = tmp_path / 'corrupt.png'
    corrupt_file.write_bytes(b'not an image')
    with pytest.raises(ValidationError, match='File is not a valid image'):
        forms.DETECT_MASK_validator(None, DummyField(str(corrupt_file)))

    # All black mask
    black_mask_file = tmp_path / 'black_mask.png'
    black_img = np.zeros((50, 50), dtype=np.uint8)
    cv2.imwrite(str(black_mask_file), black_img)
    with pytest.raises(ValidationError, match='all black'):
        forms.DETECT_MASK_validator(None, DummyField(str(black_mask_file)))

    # Valid mask with white pixels
    valid_mask_file = tmp_path / 'valid_mask.png'
    valid_img = np.zeros((50, 50), dtype=np.uint8)
    valid_img[10:20, 10:20] = 255
    cv2.imwrite(str(valid_mask_file), valid_img)
    forms.DETECT_MASK_validator(None, DummyField(str(valid_mask_file)))

    # LOGO_OVERLAY_validator
    forms.LOGO_OVERLAY_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid file name'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(tmp_path / 'logo?.png')))

    with pytest.raises(ValidationError, match='Mask file must be a PNG'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(tmp_path / 'logo.jpg')))

    with pytest.raises(ValidationError, match='File does not exist'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(tmp_path / 'missing_logo.png')))

    with pytest.raises(ValidationError, match='Not a file'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(dir_png)))

    with patch('io.open', side_effect=PermissionError('Denied')):
        with pytest.raises(ValidationError, match='Denied'):
            forms.LOGO_OVERLAY_validator(None, DummyField(str(perm_file)))

    # Corrupt logo
    with pytest.raises(ValidationError, match='File is not a valid image'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(corrupt_file)))

    # Logo without alpha channel (RGB only, 3 channels)
    no_alpha_file = tmp_path / 'no_alpha.png'
    rgb_img = np.zeros((50, 50, 3), dtype=np.uint8)
    cv2.imwrite(str(no_alpha_file), rgb_img)
    with pytest.raises(ValidationError, match='alpha channel'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(no_alpha_file)))

    # Logo without alpha channel (grayscale 2D, IndexError)
    with pytest.raises(ValidationError, match='alpha channel'):
        forms.LOGO_OVERLAY_validator(None, DummyField(str(valid_mask_file)))

    # Logo with alpha channel (RGBA, 4 channels)
    rgba_file = tmp_path / 'rgba_logo.png'
    rgba_img = np.zeros((50, 50, 4), dtype=np.uint8)
    rgba_img[:, :, 3] = 255
    cv2.imwrite(str(rgba_file), rgba_img)
    forms.LOGO_OVERLAY_validator(None, DummyField(str(rgba_file)))


def test_filetransfer_libcurl_options_validator():
    """Test FILETRANSFER__LIBCURL_OPTIONS_validator."""
    # Valid JSON with pycurl options
    valid_json = json.dumps({
        '#comment': 'a comment',
        'CURLOPT_TIMEOUT': 30,
        'CURLOPT_USERAGENT': 'indi-allsky',
    })
    forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(valid_json))

    # Invalid JSON
    with pytest.raises(ValidationError):
        forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField('not valid json'))

    # Invalid option name
    bad_opt_json = json.dumps({'CURLOPT_NONEXISTENT_OPTION_XYZ': 123})
    with pytest.raises(ValidationError, match='Invalid libcurl property'):
        forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(bad_opt_json))

    # Non-string/int value
    bad_val_json = json.dumps({'CURLOPT_TIMEOUT': [1, 2, 3]})
    with pytest.raises(ValidationError):
        forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(bad_val_json))
