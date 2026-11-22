"""Edge case tests for file, folder, font, key, and secret validators."""
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms as f_mod

Field = namedtuple('Field', ['data'])


def test_month_label_template_empty_returns():
    form = MagicMock()
    f_mod.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(form, Field(None))
    f_mod.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(form, Field(''))


def test_startrails_timelapse_minframes_too_low():
    form = MagicMock()
    with pytest.raises(ValidationError, match='must be 25 or more'):
        f_mod.STARTRAILS_TIMELAPSE_MINFRAMES_validator(form, Field(20))


def test_varlib_folder_invalid_chars():
    form = MagicMock()
    with pytest.raises(ValidationError, match='disallowed characters'):
        f_mod.VARLIB_FOLDER_validator(form, Field('/var/lib/indi-allsky;bad'))


def test_varlib_folder_trailing_slash():
    form = MagicMock()
    with pytest.raises(ValidationError, match='cannot end with slash'):
        f_mod.VARLIB_FOLDER_validator(form, Field('/var/lib/indi-allsky/'))


def test_varlib_folder_not_exist(tmp_path):
    form = MagicMock()
    non_existent = tmp_path / 'does_not_exist'
    with pytest.raises(ValidationError):
        f_mod.VARLIB_FOLDER_validator(form, Field(str(non_existent)))


def test_varlib_folder_not_a_directory(tmp_path):
    form = MagicMock()
    file_path = tmp_path / 'a_file.txt'
    file_path.write_text('hello')
    with pytest.raises(ValidationError, match='Path is not a directory'):
        f_mod.VARLIB_FOLDER_validator(form, Field(str(file_path)))


def test_varlib_folder_permission_error(tmp_path):
    form = MagicMock()
    with patch('os.path.exists', side_effect=PermissionError('Permission denied')):
        with pytest.raises(ValidationError):
            f_mod.VARLIB_FOLDER_validator(form, Field('/protected/path'))


def test_image_folder_permission_error():
    form = MagicMock()
    with patch('os.path.exists', side_effect=PermissionError('Permission denied')):
        with pytest.raises(ValidationError):
            f_mod.IMAGE_FOLDER_validator(form, Field('/protected/path'))


def test_image_export_folder_permission_error():
    form = MagicMock()
    with patch('os.path.exists', side_effect=PermissionError('Permission denied')):
        with pytest.raises(ValidationError):
            f_mod.IMAGE_EXPORT_FOLDER_validator(form, Field('/protected/path'))


def test_image_extra_text_invalid_chars():
    form = MagicMock()
    with pytest.raises(ValidationError, match='Invalid file name'):
        f_mod.IMAGE_EXTRA_TEXT_validator(form, Field('/path/with;invalid_char'))


def test_pil_font_custom_not_exists(tmp_path):
    form = MagicMock()
    non_existent = tmp_path / 'nonexistent.ttf'
    with pytest.raises(ValidationError, match='File does not exist'):
        f_mod.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(form, Field(str(non_existent)))


def test_lightgraph_rgb_invalid():
    form = MagicMock()
    with pytest.raises(ValidationError, match='Invalid syntax'):
        f_mod.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(form, Field('invalid'))


def test_image_overlay_url_no_scheme():
    form = MagicMock()
    with pytest.raises(ValidationError):
        f_mod.IMAGE_OVERLAY__URL_validator(form, Field('example.com/logo.png'))


def test_rgb_color_valid():
    form = MagicMock()
    f_mod.RGB_COLOR_validator(form, Field('255,255,255'))


def test_private_key_not_exists(tmp_path):
    form = MagicMock()
    key_file = tmp_path / 'nonexistent_rsa'
    with pytest.raises(ValidationError, match='File does not exist'):
        f_mod.FILETRANSFER__PRIVATE_KEY_validator(form, Field(str(key_file)))


def test_public_key_not_exists(tmp_path):
    form = MagicMock()
    pub_file = tmp_path / 'nonexistent_pub'
    with pytest.raises(ValidationError, match='File does not exist'):
        f_mod.FILETRANSFER__PUBLIC_KEY_validator(form, Field(str(pub_file)))


def test_filetransfer_libcurl_options_none_and_dict():
    form = MagicMock()
    f_mod.FILETRANSFER__LIBCURL_OPTIONS_validator(form, Field(None))
    f_mod.FILETRANSFER__LIBCURL_OPTIONS_validator(form, Field({}))
    f_mod.FILETRANSFER__LIBCURL_OPTIONS_validator(form, Field({'SSL_VERIFYPEER': 0}))

    with pytest.raises(ValidationError, match='Expecting value'):
        f_mod.FILETRANSFER__LIBCURL_OPTIONS_validator(form, Field('invalid_json'))


def test_s3_credentials_file_not_exist(tmp_path):
    form = MagicMock()
    cred_file = tmp_path / 'nonexistent_creds.json'
    with pytest.raises(ValidationError, match='File does not exist'):
        f_mod.S3UPLOAD__CREDS_FILE_validator(form, Field(str(cred_file)))


def test_youtube_secrets_file_not_exist(tmp_path):
    form = MagicMock()
    sec_file = tmp_path / 'nonexistent_secrets.json'
    with pytest.raises(ValidationError, match='File does not exist'):
        f_mod.YOUTUBE__SECRETS_FILE_validator(form, Field(str(sec_file)))


def test_pycurl_camera_url_no_scheme():
    form = MagicMock()
    with pytest.raises(ValidationError):
        f_mod.PYCURL_CAMERA__URL_validator(form, Field('example.com/stream'))
