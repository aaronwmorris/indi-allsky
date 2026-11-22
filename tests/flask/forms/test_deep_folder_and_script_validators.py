import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import cv2
import pycurl
from PIL import ImageFont
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


class DummyForm:
    def __init__(self):
        self.IMAGE_OVERLAY__IMAGE_FILE_TYPE_choices = [('png', 'PNG'), ('jpg', 'JPG')]
        self.LIBCAMERA__IMAGE_FILE_TYPE_choices = [('png', 'PNG'), ('jpg', 'JPG')]
        self.LIBCAMERA__AWB_choices = [('auto', 'Auto')]
        self.PYCURL_CAMERA__IMAGE_FILE_TYPE_choices = [('png', 'PNG')]
        self.CIRCULAR_DISPLAY__RESOLUTION_choices = [('1080p', '1080p')]
        self.TEMP_SENSOR__SI7021_HEATER_LEVEL_choices = [('0', 'Off'), ('1', 'Low')]
        self.TEXT_PROPERTIES__PIL_FONT_FILE_choices = [('font1.ttf', 'Font 1')]
        self.FFMPEG_CODEC_choices = [('libx264', 'H.264')]
        self.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO = DummyField(0.5)


def test_asi676mc_normalize_settings_error():
    form = DummyForm()
    with patch('indi_allsky.flask.forms.asi676mc.normalize_settings', side_effect=ValueError('Normalization failed')):
        with pytest.raises(ValidationError, match='Normalization failed'):
            forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator(form, DummyField(0.8))


def test_ccd_temp_script_validator_deep_errors(tmp_path):
    script = tmp_path / 'temp_script.sh'
    script.write_text('#!/bin/sh\n')
    script.chmod(0o755)

    # Line 586: not readable
    with patch('os.access', side_effect=lambda path, mode: False if mode == os.R_OK else True):
        with pytest.raises(ValidationError, match='Temperature script is not readable'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 591: PermissionError during stat
    with patch.object(Path, 'stat', side_effect=PermissionError('Stat denied')):
        with pytest.raises(ValidationError, match='Stat denied'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 618-619: OSError on Popen
    with patch('subprocess.Popen', side_effect=OSError('Exec error')):
        with pytest.raises(ValidationError, match='Temperature script failed to execute: Exec error'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 624-628: TimeoutExpired
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd='cmd', timeout=3.0)
    mock_proc.poll.return_value = None
    with patch('subprocess.Popen', return_value=mock_proc), patch('time.sleep'):
        with pytest.raises(ValidationError, match='Temperature script timed out'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 635: PermissionError on unlink when returncode != 0
    mock_proc_fail = MagicMock()
    mock_proc_fail.wait.return_value = 1
    mock_proc_fail.returncode = 1
    with patch('subprocess.Popen', return_value=mock_proc_fail), \
         patch.object(Path, 'unlink', side_effect=PermissionError('unlink denied')):
        with pytest.raises(ValidationError, match='Temperature script exited abnormally'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 648-649: PermissionError when reading temp JSON
    mock_proc_ok = MagicMock()
    mock_proc_ok.wait.return_value = 0
    mock_proc_ok.returncode = 0
    real_open = io.open
    def fake_open_perm(file, *args, **kwargs):
        if 'json' in str(file):
            raise PermissionError('Read JSON denied')
        return real_open(file, *args, **kwargs)

    def fake_open_fnf(file, *args, **kwargs):
        if 'json' in str(file):
            raise FileNotFoundError('No JSON file')
        return real_open(file, *args, **kwargs)

    with patch('subprocess.Popen', return_value=mock_proc_ok), \
         patch('io.open', side_effect=fake_open_perm):
        with pytest.raises(ValidationError, match='Read JSON denied'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))

    # Line 653-654: FileNotFoundError when reading temp JSON
    with patch('subprocess.Popen', return_value=mock_proc_ok), \
         patch('io.open', side_effect=fake_open_fnf):
        with pytest.raises(ValidationError, match='No JSON file'):
            forms.CCD_TEMP_SCRIPT_validator(None, DummyField(str(script)))


def test_script_validator_deep_errors(tmp_path):
    script = tmp_path / 's.sh'
    script.write_text('#!/bin/sh\n')
    script.chmod(0o755)

    # Line 683: not readable
    with patch('os.access', side_effect=lambda path, mode: False if mode == os.R_OK else True):
        with pytest.raises(ValidationError, match='Script is not readable'):
            forms.SCRIPT_validator(None, DummyField(str(script)))

    # Line 688: PermissionError
    with patch.object(Path, 'stat', side_effect=PermissionError('Script stat denied')):
        with pytest.raises(ValidationError, match='Script stat denied'):
            forms.SCRIPT_validator(None, DummyField(str(script)))


def test_image_rotate_validator_attribute_error():
    # Line 1270-1271: AttributeError in cv2
    dummy_cv2 = MagicMock(spec=[])
    with patch.dict(sys.modules, {'cv2': dummy_cv2}):
        with pytest.raises(ValidationError):
            forms.IMAGE_ROTATE_validator(None, DummyField('ROTATE_90_CLOCKWISE'))


def test_varlib_folder_validator_errors(tmp_path):
    # Lines 1529, 1532, 1535, 1537
    existing_dir = tmp_path / 'varlib_exists'
    existing_dir.mkdir()
    with patch('os.access', side_effect=lambda path, mode: False if mode == os.W_OK else True):
        with pytest.raises(ValidationError, match='Folder not writable'):
            forms.VARLIB_FOLDER_validator(None, DummyField(str(existing_dir)))

    with patch('os.access', side_effect=lambda path, mode: False if mode == os.X_OK else True):
        with pytest.raises(ValidationError, match='Folder not accessible'):
            forms.VARLIB_FOLDER_validator(None, DummyField(str(existing_dir)))

    with patch('os.access', side_effect=PermissionError('stat denied')):
        with pytest.raises(ValidationError, match='stat denied'):
            forms.VARLIB_FOLDER_validator(None, DummyField(str(existing_dir)))

    with patch('os.access', side_effect=OSError('stat os error')):
        with pytest.raises(ValidationError, match='stat os error'):
            forms.VARLIB_FOLDER_validator(None, DummyField(str(existing_dir)))


def test_image_folder_validator_errors(tmp_path):
    # Lines 1558-1562, 1583, 1586-1587
    non_existent = tmp_path / 'new_img_dir'
    with patch.object(Path, 'mkdir', side_effect=PermissionError('mkdir denied')):
        with pytest.raises(ValidationError, match='mkdir denied'):
            forms.IMAGE_FOLDER_validator(None, DummyField(str(non_existent)))

    with patch.object(Path, 'mkdir', side_effect=OSError('mkdir os error')):
        with pytest.raises(ValidationError, match='mkdir os error'):
            forms.IMAGE_FOLDER_validator(None, DummyField(str(non_existent)))

    # IMAGE_EXPORT_FOLDER PermissionError & OSError
    with patch.object(Path, 'mkdir', side_effect=PermissionError('export mkdir denied')):
        with pytest.raises(ValidationError, match='export mkdir denied'):
            forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField(str(non_existent)))

    with patch.object(Path, 'mkdir', side_effect=OSError('export mkdir os error')):
        with pytest.raises(ValidationError, match='export mkdir os error'):
            forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField(str(non_existent)))


def test_backup_db_period_days_validator():
    # Lines 1879, 1882
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.BACKUP_DB_PERIOD_DAYS_validator(None, DummyField('invalid'))
    with pytest.raises(ValidationError, match='Backups must be every 1 day or greater'):
        forms.BACKUP_DB_PERIOD_DAYS_validator(None, DummyField(0))
    forms.BACKUP_DB_PERIOD_DAYS_validator(None, DummyField(5))


def test_ffmpeg_codec_validator():
    # Line 1928
    form = DummyForm()
    forms.FFMPEG_CODEC_validator(form, DummyField('libx264'))
    with pytest.raises(ValidationError, match='Invalid codec option'):
        forms.FFMPEG_CODEC_validator(form, DummyField('invalid_codec'))


def test_text_properties_pil_font_file_validator():
    # Line 1985
    form = DummyForm()
    forms.TEXT_PROPERTIES__PIL_FONT_FILE_validator(form, DummyField('font1.ttf'))
    with pytest.raises(ValidationError, match='Invalid font selection'):
        forms.TEXT_PROPERTIES__PIL_FONT_FILE_validator(form, DummyField('invalid_font.ttf'))


def test_text_properties_pil_font_custom_validator(tmp_path):
    # Lines 2003-2004, 2006-2012
    forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(''))

    # not a file (is a dir)
    font_dir = tmp_path / 'font_dir'
    font_dir.mkdir()
    with pytest.raises(ValidationError, match='Path is not a file'):
        forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(str(font_dir)))

    font_file = tmp_path / 'custom.ttf'
    font_file.write_text('dummy content')

    # not readable
    with patch('os.access', side_effect=lambda path, mode: False if mode == os.R_OK else True):
        with pytest.raises(ValidationError, match='Font is not readable'):
            forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(str(font_file)))

    # PermissionError
    with patch.object(Path, 'is_file', side_effect=PermissionError('stat denied')):
        with pytest.raises(ValidationError, match='stat denied'):
            forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(str(font_file)))

    # OSError from truetype
    with patch('PIL.ImageFont.truetype', side_effect=OSError('Cannot open font')):
        with pytest.raises(ValidationError, match='Cannot open font'):
            forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(str(font_file)))

    # Success
    with patch('PIL.ImageFont.truetype', return_value=MagicMock()):
        forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(str(font_file)))


def test_lightgraph_overlay_rgb_color_validator():
    # Line 2130
    forms.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(None, DummyField('255,255,255'))
    with pytest.raises(ValidationError, match='Invalid syntax'):
        forms.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(None, DummyField('invalid_rgb'))
    with pytest.raises(ValidationError, match='Invalid syntax'):
        forms.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(None, DummyField('256,0,0'))
    with pytest.raises(ValidationError, match='Color cannot be'):
        forms.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(None, DummyField('0,0,0'))


def test_image_overlay_url_validator():
    # Lines 2144-2145
    forms.IMAGE_OVERLAY__URL_validator(None, DummyField(''))
    forms.IMAGE_OVERLAY__URL_validator(None, DummyField('https://example.com/logo.png'))
    mock_field = MagicMock()
    mock_field.data = 12345  # urlparse will raise AttributeError
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.IMAGE_OVERLAY__URL_validator(None, mock_field)


def test_image_overlay_image_file_type_validator():
    # Lines 2173-2174
    form = DummyForm()
    forms.IMAGE_OVERLAY__IMAGE_FILE_TYPE_validator(form, DummyField('png'))
    with pytest.raises(ValidationError, match='Please select a valid file type'):
        forms.IMAGE_OVERLAY__IMAGE_FILE_TYPE_validator(form, DummyField('gif'))


def test_rgb_color_validator_out_of_range():
    # Line 2218
    forms.RGB_COLOR_validator(None, DummyField('0,128,255'))
    with pytest.raises(ValidationError, match='Invalid syntax'):
        forms.RGB_COLOR_validator(None, DummyField('0,128,256'))


def test_adsb_dump1090_url_validator():
    # Lines 2398-2399
    forms.ADSB__DUMP1090_URL_validator(None, DummyField(''))
    forms.ADSB__DUMP1090_URL_validator(None, DummyField('http://adsb.local:8080/data'))
    mock_field = MagicMock()
    mock_field.data = 99999
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.ADSB__DUMP1090_URL_validator(None, mock_field)


def test_filetransfer_key_and_folder_validators(tmp_path):
    # Lines 2482, 2492, 2507
    key_file = tmp_path / 'id_rsa'
    key_file.write_text('key_content')

    with patch('io.open', side_effect=PermissionError('Key read denied')):
        with pytest.raises(ValidationError, match='Key read denied'):
            forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField(str(key_file)))
        with pytest.raises(ValidationError, match='Key read denied'):
            forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField(str(key_file)))

    # Lines 2535-2536, 2562-2563, 2597-2598
    with pytest.raises(ValidationError, match='Invalid filename syntax'):
        forms.FILETRANSFER__REMOTE_NAME_validator(None, DummyField('bad!name'))
    with pytest.raises(ValidationError, match='Invalid filename syntax'):
        forms.FILETRANSFER__REMOTE_METADATA_NAME_validator(None, DummyField('bad!name'))
    with pytest.raises(ValidationError, match='Invalid filename syntax'):
        forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('bad!folder'))


def test_filetransfer_libcurl_options_deep():
    # Lines 2619, 2622, 2636, 2659-2667
    # Comment in json
    valid_with_comment = json.dumps({'#a_comment': 'val', 'CURLOPT_TIMEOUT': 10})
    forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(valid_with_comment))

    # pycurl E_UNKNOWN_OPTION
    with patch('pycurl.Curl') as mock_curl_cls:
        mock_client = MagicMock()
        mock_curl_cls.return_value = mock_client
        mock_client.setopt.side_effect = pycurl.error(pycurl.E_UNKNOWN_OPTION, 'unknown option')
        with pytest.raises(ValidationError, match='Unknown libcurl option'):
            forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(json.dumps({'CURLOPT_TIMEOUT': 10})))

    # pycurl other error
    with patch('pycurl.Curl') as mock_curl_cls:
        mock_client = MagicMock()
        mock_curl_cls.return_value = mock_client
        mock_client.setopt.side_effect = pycurl.error(99, 'general error')
        with pytest.raises(ValidationError, match='Error: general error'):
            forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(json.dumps({'CURLOPT_TIMEOUT': 10})))

    # TypeError
    with patch('pycurl.Curl') as mock_curl_cls:
        mock_client = MagicMock()
        mock_curl_cls.return_value = mock_client
        mock_client.setopt.side_effect = TypeError('type error occurred')
        with pytest.raises(ValidationError, match='TypeError: TIMEOUT -  type error occurred'):
            forms.FILETRANSFER__LIBCURL_OPTIONS_validator(None, DummyField(json.dumps({'CURLOPT_TIMEOUT': 10})))


def test_s3upload_and_syncapi_validators(tmp_path):
    # Lines 2701-2702
    mock_field = MagicMock()
    mock_field.data = 123
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.S3UPLOAD__ENDPOINT_URL_validator(None, mock_field)

    # Line 2806, 2821: S3UPLOAD__CREDS_FILE_validator
    forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid file name'):
        forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField('bad?creds?file'))

    creds_file = tmp_path / 'creds.json'
    creds_file.write_text('{}')
    with patch('io.open', side_effect=PermissionError('Creds read denied')):
        with pytest.raises(ValidationError, match='Creds read denied'):
            forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField(str(creds_file)))

    # Line 2856-2857: SYNCAPI__BASEURL_validator
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.SYNCAPI__BASEURL_validator(None, mock_field)

    # Line 2906, 2921: YOUTUBE__SECRETS_FILE_validator
    forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid file name'):
        forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField('bad?secrets?file'))

    secrets_file = tmp_path / 'secrets.json'
    secrets_file.write_text('{}')
    with patch('io.open', side_effect=PermissionError('Secrets read denied')):
        with pytest.raises(ValidationError, match='Secrets read denied'):
            forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField(str(secrets_file)))


def test_libcamera_and_pycurl_validators():
    form = DummyForm()
    # Lines 2986-2987: LIBCAMERA__IMAGE_FILE_TYPE_validator
    forms.LIBCAMERA__IMAGE_FILE_TYPE_validator(form, DummyField('png'))
    with pytest.raises(ValidationError, match='Please select a valid file type'):
        forms.LIBCAMERA__IMAGE_FILE_TYPE_validator(form, DummyField('invalid'))

    # Lines 2991-2992: LIBCAMERA__AWB_validator
    forms.LIBCAMERA__AWB_validator(form, DummyField('auto'))
    with pytest.raises(ValidationError, match='Please select a valid AWB'):
        forms.LIBCAMERA__AWB_validator(form, DummyField('invalid'))

    # Line 2997: LIBCAMERA__CAMERA_ID_validator None
    forms.LIBCAMERA__CAMERA_ID_validator(form, DummyField(None))

    # Line 3017: LIBCAMERA__EXTRA_OPTIONS_validator
    forms.LIBCAMERA__EXTRA_OPTIONS_validator(form, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid characters'):
        forms.LIBCAMERA__EXTRA_OPTIONS_validator(form, DummyField('bad?options'))

    # Lines 3038-3039: PYCURL_CAMERA__URL_validator
    forms.PYCURL_CAMERA__URL_validator(form, DummyField(''))
    mock_field = MagicMock()
    mock_field.data = 123
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.PYCURL_CAMERA__URL_validator(form, mock_field)

    # Lines 3046-3047: PYCURL_CAMERA__IMAGE_FILE_TYPE_validator
    forms.PYCURL_CAMERA__IMAGE_FILE_TYPE_validator(form, DummyField('png'))
    with pytest.raises(ValidationError, match='Please select a valid file type'):
        forms.PYCURL_CAMERA__IMAGE_FILE_TYPE_validator(form, DummyField('invalid'))

    # Lines 3137-3138: CIRCULAR_DISPLAY__RESOLUTION_validator
    forms.CIRCULAR_DISPLAY__RESOLUTION_validator(form, DummyField('1080p'))
    with pytest.raises(ValidationError, match='Invalid selection'):
        forms.CIRCULAR_DISPLAY__RESOLUTION_validator(form, DummyField('invalid'))

    # Lines 3401-3402: TEMP_SENSOR__SI7021_HEATER_LEVEL_validator
    forms.TEMP_SENSOR__SI7021_HEATER_LEVEL_validator(form, DummyField(None))
    mock_bad_str = MagicMock()
    mock_bad_str.data.__str__.side_effect = ValueError('str failed')
    with pytest.raises(ValidationError, match='ValueError: str failed'):
        forms.TEMP_SENSOR__SI7021_HEATER_LEVEL_validator(form, mock_bad_str)


def test_indi_config_defaults_validator():
    # Lines 3636, 3658, 3663, 3667, 3672, 3676, 3681
    forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField(None))

    # Non-dict PROPERTIES value
    with pytest.raises(ValidationError, match='Number property PROP value must be a dict'):
        forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'PROPERTIES': {'PROP': 'not a dict'}}))

    # PROPERTIES with comment
    forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'PROPERTIES': {'PROP': {'#comment': 1, 'val': 2}}}))

    # Non-dict TEXT value
    with pytest.raises(ValidationError, match='Text property TPROP value must be a dict'):
        forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'TEXT': {'TPROP': 'not a dict'}}))

    # TEXT with comment
    forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'TEXT': {'TPROP': {'#comment': 1, 'val': 'txt'}}}))

    # Non-dict SWITCHES value
    with pytest.raises(ValidationError, match='Switch SW value must be a dict'):
        forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'SWITCHES': {'SW': 'not a dict'}}))

    # SWITCHES with comment and invalid switch config
    forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'SWITCHES': {'SW': {'#comment': 1, 'on': ['s1']}}}))

    with pytest.raises(ValidationError, match='Invalid switch configuration invalid_key'):
        forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'SWITCHES': {'SW': {'invalid_key': ['s1']}}}))

    with pytest.raises(ValidationError, match='Switch SW "on" value must be a list'):
        forms.INDI_CONFIG_DEFAULTS_validator(None, DummyField({'SWITCHES': {'SW': {'on': 'not a list'}}}))
