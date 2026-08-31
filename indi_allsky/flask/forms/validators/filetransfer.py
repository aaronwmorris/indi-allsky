import os
from pathlib import Path
import io
import re
import json
import math
import time
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import tempfile
from urllib.parse import urlparse
import psutil
import subprocess
import itertools
import dbus

from passlib.hash import argon2

from indi_allsky import constants
from indi_allsky import asi676mc
from indi_allsky import asi676mc_calibration

from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms import FloatField
from wtforms import BooleanField
from wtforms import SelectField
from wtforms import StringField
from wtforms import PasswordField
from wtforms import TextAreaField
from wtforms import HiddenField
from wtforms import DateTimeLocalField
from wtforms import FileField
from wtforms.widgets import PasswordInput
from wtforms.widgets import NumberInput
from wtforms.validators import DataRequired
from wtforms.validators import NumberRange
#from wtforms.validators import regexp as validator_regexp
from wtforms.validators import ValidationError
from markupsafe import Markup

from sqlalchemy import extract
#from sqlalchemy import asc
from sqlalchemy import func
#from sqlalchemy.types import DateTime
#from sqlalchemy.types import Date
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import false as sa_false
from sqlalchemy.sql.expression import null as sa_null

from flask import current_app as app
from flask import url_for

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbRawImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable
from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable

from indi_allsky.flask import db


def BACKUP_DB_PERIOD_DAYS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Backups must be every 1 day or greater')


def UPLOAD_WORKERS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Worker count must be 1 or greater')

    if field.data > 4:
        raise ValidationError('Worker count must be less than 5')


def FILETRANSFER__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.FILETRANSFER__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def FILETRANSFER__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\ \@\.\-\\]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def FILETRANSFER__PASSWORD_validator(form, field):
    pass


def FILETRANSFER__TIMEOUT_validator(form, field):
    if field.data < 1:
        raise ValidationError('Timeout must be 1.0 or greater')

    if field.data > 1200:
        raise ValidationError('Timeout must be 1200 or less')


def S3UPLOAD__TIMEOUT_validator(form, field):
    if field.data < 1:
        raise ValidationError('Timeout must be 1.0 or greater')

    if field.data > 1200:
        raise ValidationError('Timeout must be 1200 or less')


def FILETRANSFER__PRIVATE_KEY_validator(form, field):
    if not field.data:
        return

    file_name_regex = r'^[a-zA-Z0-9_\.\-\/]+$'

    if not re.search(file_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


    file_name_p = Path(field.data)

    try:
        if not file_name_p.exists():
            raise ValidationError('File does not exist')

        if not file_name_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(file_name_p), 'rb'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def FILETRANSFER__PUBLIC_KEY_validator(form, field):
    if not field.data:
        return

    file_name_regex = r'^[a-zA-Z0-9_\.\-\/]+$'

    if not re.search(file_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


    file_name_p = Path(field.data)

    try:
        if not file_name_p.exists():
            raise ValidationError('File does not exist')

        if not file_name_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(file_name_p), 'rb'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def FILETRANSFER__REMOTE_NAME_validator(form, field):
    image_name_regex = r'^[a-zA-Z0-9_\.\-\{\}\:\%]+$'

    if not re.search(image_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


    now = datetime.now()

    test_list = ['jpg']
    test_data = {
        'timestamp'  : now,
        'ts'         : now,
        'ext'        : 'jpg',
        'day_date'   : now.date(),
        'camera_uuid': '',
        'camera_id'  : 0,
        'timeofday'  : 'night',
        'tod'        : 'night',
    }

    try:
        field.data.format(*test_list, **test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def FILETRANSFER__REMOTE_METADATA_NAME_validator(form, field):
    metadata_name_regex = r'^[a-zA-Z0-9_\.\-\{\}\:\%]+$'

    if not re.search(metadata_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


    now = datetime.now()

    test_data = {
        'timestamp'  : now,
        'ts'         : now,
        'day_date'   : now.date(),
        'camera_uuid': '',
        'camera_id'  : 0,
        'timeofday'  : 'night',
        'tod'        : 'night',
    }

    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def FILETRANSFER__REMOTE_FOLDER_validator(form, field):
    folder_regex = r'^[a-zA-Z0-9_\ \.\-\/\{\}\:\%\~]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid filename syntax')


    if re.search(r'//', field.data):
        raise ValidationError('Remove double // in folder name')


    if re.search(r'\/$', field.data):
        raise ValidationError('Folder cannot end with a slash')


    now = datetime.now()

    test_data = {
        'timestamp'  : now,
        'ts'         : now,
        'day_date'   : now.date(),
        'camera_uuid': '',
        'camera_id'  : 0,
        'timeofday'  : 'night',
        'tod'        : 'night',
    }

    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def FILETRANSFER__UPLOAD_IMAGE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Image Upload must be 0 or greater')


def FILETRANSFER__LIBCURL_OPTIONS_validator(form, field):
    try:
        json_data = json.loads(field.data)
    except json.decoder.JSONDecodeError as e:
        raise ValidationError(str(e))


    import pycurl
    client = pycurl.Curl()  # test client


    for k, v in json_data.items():
        if not isinstance(k, str):
            raise ValidationError('Property names must be a str')

        if not isinstance(v, (str, int)):
            raise ValidationError('Property {0:s} value must be a str or int'.format(k))


        if k.startswith('#'):
            # comment
            continue


        if k.startswith('CURLOPT_'):
            # remove CURLOPT_ prefix
            k = k[8:]


        try:
            curlopt = getattr(pycurl, k)
        except AttributeError:
            raise ValidationError('Invalid libcurl property: {0:s}'.format(k))

        try:
            client.setopt(curlopt, v)
        except pycurl.error as e:
            rc, msg = e.args

            if rc in [pycurl.E_UNKNOWN_OPTION]:
                raise ValidationError('Unknown libcurl option {0:s}'.format(k))
            else:
                raise ValidationError('Error: {0:s}'.format(msg))
        except TypeError as e:
            raise ValidationError('TypeError: {0:s} -  {1:s}'.format(k, str(e)))


def S3UPLOAD__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.S3UPLOAD__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def S3UPLOAD__ACCESS_KEY_validator(form, field):
    if not field.data:
        return

    s3accesskey_regex = r'^[a-zA-Z0-9]+$'

    if not re.search(s3accesskey_regex, field.data):
        raise ValidationError('Invalid access key')


def S3UPLOAD__SECRET_KEY_validator(form, field):
    if not field.data:
        return

    s3secretkey_regex = r'^[a-zA-Z0-9\/\+]+$'

    if not re.search(s3secretkey_regex, field.data):
        raise ValidationError('Invalid secret key')


def S3UPLOAD__ENDPOINT_URL_validator(form, field):
    if not field.data:
        return

    try:
        r = urlparse(field.data)
    except AttributeError:
        raise ValidationError('Invalid URL')

    if not r.scheme:
        raise ValidationError('Invalid URL')


def S3UPLOAD__REGION_validator(form, field):
    if not field.data:
        return

    region_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(region_regex, field.data):
        raise ValidationError('Invalid region name')


def S3UPLOAD__BUCKET_validator(form, field):
    bucket_regex = r'^[a-zA-Z0-9\.\-]+$'

    if not re.search(bucket_regex, field.data):
        raise ValidationError('Invalid bucket name')


def S3UPLOAD__NAMESPACE_validator(form, field):
    if not field.data:
        return

    namespace_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(namespace_regex, field.data):
        raise ValidationError('Invalid namespace name')


def S3UPLOAD__ACL_validator(form, field):
    if not field.data:
        return

    acl_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(acl_regex, field.data):
        raise ValidationError('Invalid ACL name')


def S3UPLOAD__STORAGE_CLASS_validator(form, field):
    if not field.data:
        return

    class_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(class_regex, field.data):
        raise ValidationError('Invalid storage class syntax')


def S3UPLOAD__CREDS_FILE_validator(form, field):
    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')


    creds_p = Path(field.data)

    try:
        if not creds_p.exists():
            raise ValidationError('File does not exist')

        if not creds_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(creds_p), 'r'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def YOUTUBE__SECRETS_FILE_validator(form, field):
    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')


    secrets_p = Path(field.data)

    try:
        if not secrets_p.exists():
            raise ValidationError('File does not exist')

        if not secrets_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(secrets_p), 'r'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def YOUTUBE__PRIVACY_STATUS_validator(form, field):
    if field.data not in list(zip(*form.YOUTUBE__PRIVACY_STATUS_choices))[0]:
        raise ValidationError('Please select a privacy status')


def YOUTUBE__CATEGORY_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid category number')


def YOUTUBE__TAGS_STR_validator(form, field):
    if not field.data:
        return


