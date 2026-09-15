from pathlib import Path
import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_border_and_worker_validators():
    # IMAGE_BORDER_SIDE_validator
    with pytest.raises(ValidationError, match='Border must be 0 or greater'):
        forms.IMAGE_BORDER_SIDE_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Border must be less than 1000'):
        forms.IMAGE_BORDER_SIDE_validator(None, DummyField(1001))
    forms.IMAGE_BORDER_SIDE_validator(None, DummyField(10))

    # UPLOAD_WORKERS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.UPLOAD_WORKERS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Worker count must be 1 or greater'):
        forms.UPLOAD_WORKERS_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Worker count must be less than 5'):
        forms.UPLOAD_WORKERS_validator(None, DummyField(5))
    forms.UPLOAD_WORKERS_validator(None, DummyField(2))


def test_host_and_port_validators():
    # FILETRANSFER__HOST_validator
    forms.FILETRANSFER__HOST_validator(None, DummyField(''))
    forms.FILETRANSFER__HOST_validator(None, DummyField('ftp.example.com'))
    with pytest.raises(ValidationError, match='Invalid host name'):
        forms.FILETRANSFER__HOST_validator(None, DummyField('invalid host!@#'))

    # MQTTPUBLISH__HOST_validator
    forms.MQTTPUBLISH__HOST_validator(None, DummyField(''))
    forms.MQTTPUBLISH__HOST_validator(None, DummyField('mqtt.example.com'))
    with pytest.raises(ValidationError, match='Invalid host name'):
        forms.MQTTPUBLISH__HOST_validator(None, DummyField('invalid host!@#'))

    # FILETRANSFER__PORT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FILETRANSFER__PORT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Port must be 0 or greater'):
        forms.FILETRANSFER__PORT_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Port must be less than 65535'):
        forms.FILETRANSFER__PORT_validator(None, DummyField(65536))
    forms.FILETRANSFER__PORT_validator(None, DummyField(21))

    # MQTTPUBLISH__PORT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MQTTPUBLISH__PORT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Port must be 1 or greater'):
        forms.MQTTPUBLISH__PORT_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Port must be less than 65535'):
        forms.MQTTPUBLISH__PORT_validator(None, DummyField(65536))
    forms.MQTTPUBLISH__PORT_validator(None, DummyField(1883))


def test_username_and_auth_validators():
    # FILETRANSFER__USERNAME_validator
    forms.FILETRANSFER__USERNAME_validator(None, DummyField(''))
    forms.FILETRANSFER__USERNAME_validator(None, DummyField('user@domain.com'))
    with pytest.raises(ValidationError, match='Invalid username'):
        forms.FILETRANSFER__USERNAME_validator(None, DummyField('user!#$%'))

    # MQTTPUBLISH__USERNAME_validator
    forms.MQTTPUBLISH__USERNAME_validator(None, DummyField(''))
    forms.MQTTPUBLISH__USERNAME_validator(None, DummyField('mqtt_user.123'))
    with pytest.raises(ValidationError, match='Invalid username'):
        forms.MQTTPUBLISH__USERNAME_validator(None, DummyField('user!#$%'))

    # SYNCAPI__USERNAME_validator
    forms.SYNCAPI__USERNAME_validator(None, DummyField(''))
    forms.SYNCAPI__USERNAME_validator(None, DummyField('sync_user'))
    with pytest.raises(ValidationError, match='Invalid username'):
        forms.SYNCAPI__USERNAME_validator(None, DummyField('user!#$%'))

    # PYCURL_CAMERA__USERNAME_validator
    forms.PYCURL_CAMERA__USERNAME_validator(None, DummyField(''))
    forms.PYCURL_CAMERA__USERNAME_validator(None, DummyField('cam_user'))
    with pytest.raises(ValidationError, match='Invalid username'):
        forms.PYCURL_CAMERA__USERNAME_validator(None, DummyField('user!#$%'))

    # ADSB__USERNAME_validator
    forms.ADSB__USERNAME_validator(None, DummyField(''))
    forms.ADSB__USERNAME_validator(None, DummyField('adsb_user'))
    with pytest.raises(ValidationError, match='Invalid username'):
        forms.ADSB__USERNAME_validator(None, DummyField('user!#$%'))

    # ADSB__DUMP1090_URL_validator
    with pytest.raises(ValidationError, match='Invalid URL'):
        forms.ADSB__DUMP1090_URL_validator(None, DummyField('noscheme_url'))


def test_timeout_and_exposure_validators():
    # ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sub-Exposure must be 1.0 or more'):
        forms.ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(None, DummyField(0.5))
    with pytest.raises(ValidationError, match='Sub-Exposure must be 60.0 or less'):
        forms.ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(None, DummyField(65.0))
    forms.ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(None, DummyField(10.0))

    # FILETRANSFER__TIMEOUT_validator
    with pytest.raises(ValidationError, match='Timeout must be 1.0 or greater'):
        forms.FILETRANSFER__TIMEOUT_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Timeout must be 1200 or less'):
        forms.FILETRANSFER__TIMEOUT_validator(None, DummyField(1201))
    forms.FILETRANSFER__TIMEOUT_validator(None, DummyField(30))

    # S3UPLOAD__TIMEOUT_validator
    with pytest.raises(ValidationError, match='Timeout must be 1.0 or greater'):
        forms.S3UPLOAD__TIMEOUT_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Timeout must be 1200 or less'):
        forms.S3UPLOAD__TIMEOUT_validator(None, DummyField(1201))
    forms.S3UPLOAD__TIMEOUT_validator(None, DummyField(30))

    # SYNCAPI__TIMEOUT_validator
    with pytest.raises(ValidationError, match='Timeout must be 1.0 or greater'):
        forms.SYNCAPI__TIMEOUT_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Timeout must be 1200 or less'):
        forms.SYNCAPI__TIMEOUT_validator(None, DummyField(1201))
    forms.SYNCAPI__TIMEOUT_validator(None, DummyField(30))


def test_filetransfer_templates_and_keys(tmp_path):
    # FILETRANSFER__PRIVATE_KEY_validator
    forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid filename syntax'):
        forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField('bad!key!'))
    with pytest.raises(ValidationError, match='File does not exist'):
        forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField(str(tmp_path / 'missing_key')))
    dir_key = tmp_path / 'dir_key'
    dir_key.mkdir()
    with pytest.raises(ValidationError, match='Not a file'):
        forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField(str(dir_key)))

    # FILETRANSFER__PUBLIC_KEY_validator
    forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField(''))
    with pytest.raises(ValidationError, match='Invalid filename syntax'):
        forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField('bad!key!'))
    with pytest.raises(ValidationError, match='File does not exist'):
        forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField(str(tmp_path / 'missing_key')))
    with pytest.raises(ValidationError, match='Not a file'):
        forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField(str(dir_key)))

    # FILETRANSFER__REMOTE_NAME_validator
    forms.FILETRANSFER__REMOTE_NAME_validator(None, DummyField('allsky_{timestamp:%Y%m%d}.{0}'))
    with pytest.raises(ValidationError, match='KeyError'):
        forms.FILETRANSFER__REMOTE_NAME_validator(None, DummyField('allsky_{unknown_key}.jpg'))
    with pytest.raises(ValidationError, match='ValueError'):
        forms.FILETRANSFER__REMOTE_NAME_validator(None, DummyField('allsky_{camera_id:s}.jpg'))

    # FILETRANSFER__REMOTE_METADATA_NAME_validator
    forms.FILETRANSFER__REMOTE_METADATA_NAME_validator(None, DummyField('meta_{timestamp:%Y%m%d}.json'))
    with pytest.raises(ValidationError, match='KeyError'):
        forms.FILETRANSFER__REMOTE_METADATA_NAME_validator(None, DummyField('meta_{unknown_key}.json'))
    with pytest.raises(ValidationError, match='ValueError'):
        forms.FILETRANSFER__REMOTE_METADATA_NAME_validator(None, DummyField('meta_{camera_id:s}.json'))

    # FILETRANSFER__REMOTE_FOLDER_validator
    forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('/allsky/{day_date:%Y%m%d}'))
    with pytest.raises(ValidationError, match='Remove double //'):
        forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('/allsky//folder'))
    with pytest.raises(ValidationError, match='Folder cannot end with a slash'):
        forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('/allsky/folder/'))
    with pytest.raises(ValidationError, match='KeyError'):
        forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('/allsky/{unknown_key}'))
    with pytest.raises(ValidationError, match='ValueError'):
        forms.FILETRANSFER__REMOTE_FOLDER_validator(None, DummyField('/allsky/{camera_id:s}'))

    # FILETRANSFER__UPLOAD_IMAGE_validator & SYNCAPI__UPLOAD_IMAGE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FILETRANSFER__UPLOAD_IMAGE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Image Upload must be 0 or greater'):
        forms.FILETRANSFER__UPLOAD_IMAGE_validator(None, DummyField(-1))
    forms.FILETRANSFER__UPLOAD_IMAGE_validator(None, DummyField(1))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SYNCAPI__UPLOAD_IMAGE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Image Upload must be 0 or greater'):
        forms.SYNCAPI__UPLOAD_IMAGE_validator(None, DummyField(-1))
    forms.SYNCAPI__UPLOAD_IMAGE_validator(None, DummyField(1))
