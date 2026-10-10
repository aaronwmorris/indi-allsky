from pathlib import Path
from unittest.mock import MagicMock
import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


class DummyMapForm:
    def __init__(self, enabled=False):
        self.ALLSKYMAP__ENABLE = DummyField(enabled)


def test_s3_validators(tmp_path):
    # S3UPLOAD__ACCESS_KEY_validator
    forms.S3UPLOAD__ACCESS_KEY_validator(None, DummyField(''))
    forms.S3UPLOAD__ACCESS_KEY_validator(None, DummyField('AKIAIOSFODNN7EXAMPLE'))
    with pytest.raises(ValidationError, match='Invalid access key'):
        forms.S3UPLOAD__ACCESS_KEY_validator(None, DummyField('bad!key!'))

    # S3UPLOAD__SECRET_KEY_validator
    forms.S3UPLOAD__SECRET_KEY_validator(None, DummyField(''))
    forms.S3UPLOAD__SECRET_KEY_validator(None, DummyField('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY+1'))
    with pytest.raises(ValidationError, match='Invalid secret key'):
        forms.S3UPLOAD__SECRET_KEY_validator(None, DummyField('bad!secret!'))

    # S3UPLOAD__HOST_validator
    forms.S3UPLOAD__HOST_validator(None, DummyField('s3.amazonaws.com'))
    with pytest.raises(ValidationError, match='Invalid host name'):
        forms.S3UPLOAD__HOST_validator(None, DummyField('bad!host!'))

    # S3UPLOAD__PORT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.S3UPLOAD__PORT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Port must be 0 or greater'):
        forms.S3UPLOAD__PORT_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Port must be less than 65535'):
        forms.S3UPLOAD__PORT_validator(None, DummyField(65536))
    forms.S3UPLOAD__PORT_validator(None, DummyField(443))

    # S3UPLOAD__REGION_validator
    forms.S3UPLOAD__REGION_validator(None, DummyField(''))
    forms.S3UPLOAD__REGION_validator(None, DummyField('us-east-1'))
    with pytest.raises(ValidationError, match='Invalid region name'):
        forms.S3UPLOAD__REGION_validator(None, DummyField('bad!region!'))

    # S3UPLOAD__BUCKET_validator
    forms.S3UPLOAD__BUCKET_validator(None, DummyField('my-allsky-bucket'))
    with pytest.raises(ValidationError, match='Invalid bucket name'):
        forms.S3UPLOAD__BUCKET_validator(None, DummyField('bad!bucket!'))

    # S3UPLOAD__NAMESPACE_validator
    forms.S3UPLOAD__NAMESPACE_validator(None, DummyField(''))
    forms.S3UPLOAD__NAMESPACE_validator(None, DummyField('allsky-cam1'))
    with pytest.raises(ValidationError, match='Invalid namespace name'):
        forms.S3UPLOAD__NAMESPACE_validator(None, DummyField('bad!namespace!'))

    # S3UPLOAD__URL_TEMPLATE_validator
    forms.S3UPLOAD__URL_TEMPLATE_validator(None, DummyField('https://{host}/{bucket}/{namespace}'))
    with pytest.raises(ValidationError, match='URL Template cannot end with a slash'):
        forms.S3UPLOAD__URL_TEMPLATE_validator(None, DummyField('https://{host}/{bucket}/'))
    with pytest.raises(ValidationError, match='KeyError'):
        forms.S3UPLOAD__URL_TEMPLATE_validator(None, DummyField('https://{host}/{badkey}'))
    with pytest.raises(ValidationError, match='ValueError'):
        forms.S3UPLOAD__URL_TEMPLATE_validator(None, DummyField('https://{host:d}'))

    # S3UPLOAD__ACL_validator
    forms.S3UPLOAD__ACL_validator(None, DummyField(''))
    forms.S3UPLOAD__ACL_validator(None, DummyField('public-read'))
    with pytest.raises(ValidationError, match='Invalid ACL name'):
        forms.S3UPLOAD__ACL_validator(None, DummyField('bad!acl!'))

    # S3UPLOAD__STORAGE_CLASS_validator
    forms.S3UPLOAD__STORAGE_CLASS_validator(None, DummyField(''))
    forms.S3UPLOAD__STORAGE_CLASS_validator(None, DummyField('STANDARD-IA'))
    with pytest.raises(ValidationError, match='Invalid storage class syntax'):
        forms.S3UPLOAD__STORAGE_CLASS_validator(None, DummyField('bad!class!'))

    # S3UPLOAD__CREDS_FILE_validator
    with pytest.raises(ValidationError, match='File does not exist'):
        forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField(str(tmp_path / 'missing_creds.json')))
    dir_creds = tmp_path / 'dir_creds'
    dir_creds.mkdir()
    with pytest.raises(ValidationError, match='Not a file'):
        forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField(str(dir_creds)))


def test_mqtt_and_syncapi_validators():
    # MQTTPUBLISH__BASE_TOPIC_validator
    forms.MQTTPUBLISH__BASE_TOPIC_validator(None, DummyField('indi-allsky/cam1'))
    with pytest.raises(ValidationError, match='Invalid characters in base topic'):
        forms.MQTTPUBLISH__BASE_TOPIC_validator(None, DummyField('bad#topic'))
    with pytest.raises(ValidationError, match='Base topic cannot begin with slash'):
        forms.MQTTPUBLISH__BASE_TOPIC_validator(None, DummyField('/indi-allsky/cam1'))
    with pytest.raises(ValidationError, match='Base topic cannot end with slash'):
        forms.MQTTPUBLISH__BASE_TOPIC_validator(None, DummyField('indi-allsky/cam1/'))

    # MQTTPUBLISH__TOPIC_validator
    forms.MQTTPUBLISH__TOPIC_validator(None, DummyField('status'))
    with pytest.raises(ValidationError, match='Topic cannot begin with slash'):
        forms.MQTTPUBLISH__TOPIC_validator(None, DummyField('/status'))
    with pytest.raises(ValidationError, match='Topic cannot end with slash'):
        forms.MQTTPUBLISH__TOPIC_validator(None, DummyField('status/'))

    # MQTTPUBLISH__QOS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MQTTPUBLISH__QOS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Invalid QoS'):
        forms.MQTTPUBLISH__QOS_validator(None, DummyField(3))
    forms.MQTTPUBLISH__QOS_validator(None, DummyField(1))

    # SYNCAPI__BASEURL_validator
    forms.SYNCAPI__BASEURL_validator(None, DummyField('https://sync.example.com/api'))
    with pytest.raises(ValidationError, match='URL should begin with https://'):
        forms.SYNCAPI__BASEURL_validator(None, DummyField('http://sync.example.com/api'))
    with pytest.raises(ValidationError, match='URL cannot end with slash'):
        forms.SYNCAPI__BASEURL_validator(None, DummyField('https://sync.example.com/api/'))
    with pytest.raises(ValidationError, match='Do not sync to localhost'):
        forms.SYNCAPI__BASEURL_validator(None, DummyField('https://localhost/api'))
    with pytest.raises(ValidationError, match='Do not sync to localhost'):
        forms.SYNCAPI__BASEURL_validator(None, DummyField('https://127.0.0.1/api'))


def test_allskymap_validators():
    form_enabled = DummyMapForm(enabled=True)
    form_disabled = DummyMapForm(enabled=False)

    # ALLSKYMAP__API_URL_validator
    forms.ALLSKYMAP__API_URL_validator(form_disabled, DummyField(''))
    with pytest.raises(ValidationError, match='API URL is required'):
        forms.ALLSKYMAP__API_URL_validator(form_enabled, DummyField(''))
    forms.ALLSKYMAP__API_URL_validator(form_enabled, DummyField('https://map.example.com/api'))
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.ALLSKYMAP__API_URL_validator(form_enabled, DummyField('ftp://map.example.com'))

    # ALLSKYMAP__API_KEY_validator
    forms.ALLSKYMAP__API_KEY_validator(form_disabled, DummyField(''))
    with pytest.raises(ValidationError, match='API Key is required'):
        forms.ALLSKYMAP__API_KEY_validator(form_enabled, DummyField(''))
    forms.ALLSKYMAP__API_KEY_validator(form_enabled, DummyField('secret_key_123'))

    # ALLSKYMAP__INTERVAL_validator
    forms.ALLSKYMAP__INTERVAL_validator(None, DummyField(None))
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.ALLSKYMAP__INTERVAL_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.ALLSKYMAP__INTERVAL_validator(None, DummyField(0))
    forms.ALLSKYMAP__INTERVAL_validator(None, DummyField(5))


def test_youtube_and_fitsheader(tmp_path):
    # YOUTUBE__SECRETS_FILE_validator
    with pytest.raises(ValidationError, match='File does not exist'):
        forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField(str(tmp_path / 'missing_yt.json')))
    dir_yt = tmp_path / 'dir_yt'
    dir_yt.mkdir()
    with pytest.raises(ValidationError, match='Not a file'):
        forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField(str(dir_yt)))

    # FITSHEADER_KEY_validator
    forms.FITSHEADER_KEY_validator(None, DummyField('OBSERVER'))
    with pytest.raises(ValidationError, match='Invalid characters in header'):
        forms.FITSHEADER_KEY_validator(None, DummyField('OBS@KEY'))
    with pytest.raises(ValidationError, match='Header must be 8 characters or less'):
        forms.FITSHEADER_KEY_validator(None, DummyField('LONGERTHANEIGHT'))


def test_libcamera_and_testcamera():
    # LIBCAMERA__CAMERA_ID_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.LIBCAMERA__CAMERA_ID_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Invalid camera id'):
        forms.LIBCAMERA__CAMERA_ID_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Invalid camera id'):
        forms.LIBCAMERA__CAMERA_ID_validator(None, DummyField(5))
    forms.LIBCAMERA__CAMERA_ID_validator(None, DummyField(0))

    # LIBCAMERA__EXTRA_OPTIONS_validator
    forms.LIBCAMERA__EXTRA_OPTIONS_validator(None, DummyField('--tuning-file file.json'))
    with pytest.raises(ValidationError, match='Options cannot begin with a space'):
        forms.LIBCAMERA__EXTRA_OPTIONS_validator(None, DummyField(' --option'))
    with pytest.raises(ValidationError, match='Options cannot end with a space'):
        forms.LIBCAMERA__EXTRA_OPTIONS_validator(None, DummyField('--option '))
    with pytest.raises(ValidationError, match='multiple concurrent space'):
        forms.LIBCAMERA__EXTRA_OPTIONS_validator(None, DummyField('--option  two'))

    # TEST_CAMERA__WIDTH_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__WIDTH_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Width must be 100 or greater'):
        forms.TEST_CAMERA__WIDTH_validator(None, DummyField(50))
    forms.TEST_CAMERA__WIDTH_validator(None, DummyField(1920))

    # TEST_CAMERA__HEIGHT_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__HEIGHT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Height must be 100 or greater'):
        forms.TEST_CAMERA__HEIGHT_validator(None, DummyField(50))
    forms.TEST_CAMERA__HEIGHT_validator(None, DummyField(1080))

    # TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Image Circle must be 0 or greater'):
        forms.TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator(None, DummyField(-1))
    forms.TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator(None, DummyField(1000))

    # TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator(None, DummyField('abc'))
    forms.TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator(None, DummyField(0))

    # TEST_CAMERA__ROTATING_STAR_COUNT_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__ROTATING_STAR_COUNT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Count must be 100 or greater'):
        forms.TEST_CAMERA__ROTATING_STAR_COUNT_validator(None, DummyField(50))
    forms.TEST_CAMERA__ROTATING_STAR_COUNT_validator(None, DummyField(500))

    # TEST_CAMERA__ROTATING_STAR_FACTOR_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TEST_CAMERA__ROTATING_STAR_FACTOR_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Factor must be greater than 0'):
        forms.TEST_CAMERA__ROTATING_STAR_FACTOR_validator(None, DummyField(0.0))
    forms.TEST_CAMERA__ROTATING_STAR_FACTOR_validator(None, DummyField(1.0))

    # TEST_CAMERA__BUBBLE_COUNT_validator
    with pytest.raises(ValidationError, match='Please enter a valid number'):
        forms.TEST_CAMERA__BUBBLE_COUNT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Count must be 10 or greater'):
        forms.TEST_CAMERA__BUBBLE_COUNT_validator(None, DummyField(5))
    forms.TEST_CAMERA__BUBBLE_COUNT_validator(None, DummyField(20))
