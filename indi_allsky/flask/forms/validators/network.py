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


def SQLALCHEMY_DATABASE_URI_validator(form, field):
    host_regex = r'^[a-zA-Z0-9_\.\-\:\/\@]+$'

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid URI')


def INDI_SERVER_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9_\.\-]+$'  # include _ for docker

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def INDI_PORT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Port must be 0 or greater')

    if field.data > 65535:
        raise ValidationError('Port must be less than 65535')


def TIMELAPSE_SKIP_FRAMES_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Skip frames must 0 or more')

    if field.data > 10:
        raise ValidationError('Skip frames must 10 or less')


def CCD_TEMP_SCRIPT_validator(form, field):
    if not field.data:
        return


    temp_script_p = Path(field.data)

    try:
        if not temp_script_p.exists():
            raise ValidationError('Temperature script does not exist')

        if not temp_script_p.is_file():
            raise ValidationError('Temperature script is not a file')

        if temp_script_p.stat().st_size == 0:
            raise ValidationError('Temperature script is empty')

        if not os.access(str(temp_script_p), os.R_OK):
            raise ValidationError('Temperature script is not readable')

        if not os.access(str(temp_script_p), os.X_OK):
            raise ValidationError('Temperature script is not executable')
    except PermissionError as e:
        raise ValidationError(str(e))


    # generate a tempfile for the data
    f_tmp_tempjson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
    f_tmp_tempjson.close()

    tempjson_name_p = Path(f_tmp_tempjson.name)


    cmd = [
        str(temp_script_p),
    ]


    # the file used for the json data is communicated via environment variable
    cmd_env = {
        'TEMP_JSON' : str(tempjson_name_p),
    }

    try:
        temp_process = subprocess.Popen(
            cmd,
            env=cmd_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise ValidationError('Temperature script failed to execute: {0:s}'.format(str(e)))


    try:
        temp_process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        temp_process.kill()
        time.sleep(1.0)
        temp_process.poll()  # close out process
        raise ValidationError('Temperature script timed out')


    if temp_process.returncode != 0:
        try:
            tempjson_name_p.unlink()  # remove temp file
        except PermissionError:
            pass
        except FileNotFoundError:
            pass

        raise ValidationError('Temperature script exited abnormally')


    try:
        with io.open(str(tempjson_name_p), 'r', encoding='utf-8') as tempjson_name_f:
            temp_data = json.load(tempjson_name_f)

        tempjson_name_p.unlink()  # remove temp file
    except PermissionError as e:
        app.logger.error(str(e))
        raise ValidationError(str(e))
    except json.JSONDecodeError as e:
        app.logger.error('Error decoding json: %s', str(e))
        raise ValidationError(str(e))
    except FileNotFoundError as e:
        raise ValidationError(str(e))


    try:
        float(temp_data['temp'])
    except ValueError:
        raise ValidationError('Temperature script returned a non-numerical value')
    except KeyError:
        raise ValidationError('Temperature script returned incorrect data')


def SCRIPT_validator(form, field):
    if not field.data:
        return


    script_p = Path(field.data)

    try:
        if not script_p.exists():
            raise ValidationError('Script does not exist')

        if not script_p.is_file():
            raise ValidationError('Script is not a file')

        if script_p.stat().st_size == 0:
            raise ValidationError('Script is empty')

        if not os.access(str(script_p), os.R_OK):
            raise ValidationError('Script is not readable')

        if not os.access(str(script_p), os.X_OK):
            raise ValidationError('Script is not executable')
    except PermissionError as e:
        raise ValidationError(str(e))


def CLAHE_CLIPLIMIT_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Clip limit must be greater than 0')

    if field.data > 60:
        raise ValidationError('Clip limit must be less than 60')


def WEBSOCKET_API_KEY_validator(form, field):
    if not field.data:
        return

    key_regex = r'^[a-zA-Z0-9_\-]+$'
    if not re.search(key_regex, field.data):
        raise ValidationError('API key can only contain letters, numbers, underscores, and hyphens')


def IMAGE_STRETCH__MODE3_BLACK_CLIP_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -10:
        raise ValidationError('Value must be -10.0 or greater')

    if field.data > 0:
        raise ValidationError('Value must be 0.0 or less')


def IMAGE_EXPORT_FOLDER_validator(form, field):
    folder_regex = r'[^a-zA-Z0-9_\.\-\/]'

    m = re.findall(folder_regex, field.data)
    if m:
        raise ValidationError('Folder contains disallowed characters: {0:s}'.format(', '.join(set(m))))

    if re.search(r'\/$', field.data):
        raise ValidationError('Directory cannot end with slash')


    image_folder_p = Path(field.data)

    try:
        if not image_folder_p.exists():
            image_folder_p.mkdir(mode=0o755, parents=True)

        if not image_folder_p.is_dir():
            raise ValidationError('Path is not a directory')
    except PermissionError as e:
        raise ValidationError(str(e))
    except OSError as e:
        raise ValidationError(str(e))


def IMAGE_EXPORT_RAW_validator(form, field):
    if not field.data:
        return

    if field.data not in ('png', 'tif', 'jpg', 'jp2', 'webp'):
        raise ValidationError('Please select a valid file type')


def FILETRANSFER__HOST_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9_\.\-\:\[\]]+$'  # include _ for docker

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def MQTTPUBLISH__TRANSPORT_validator(form, field):
    if field.data not in list(zip(*form.MQTTPUBLISH__TRANSPORT_choices))[0]:
        raise ValidationError('Invalid transport')


def MQTTPUBLISH__PROTOCOL_validator(form, field):
    if field.data not in list(zip(*form.MQTTPUBLISH__PROTOCOL_choices))[0]:
        raise ValidationError('Invalid protocol')


def MQTTPUBLISH__HOST_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9_\.\-\:\[\]]+$'  # include _ for docker

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def FILETRANSFER__PORT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Port must be 0 or greater')

    if field.data > 65535:
        raise ValidationError('Port must be less than 65535')


def MQTTPUBLISH__PORT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Port must be 1 or greater')

    if field.data > 65535:
        raise ValidationError('Port must be less than 65535')


def MQTTPUBLISH__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def SYNCAPI__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def MQTTPUBLISH__PASSWORD_validator(form, field):
    pass


def SYNCAPI__APIKEY_validator(form, field):
    pass


def SYNCAPI__TIMEOUT_validator(form, field):
    if field.data < 1:
        raise ValidationError('Timeout must be 1.0 or greater')

    if field.data > 1200:
        raise ValidationError('Timeout must be 1200 or less')


def SYNCAPI__UPLOAD_IMAGE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Image Upload must be 0 or greater')


def S3UPLOAD__HOST_validator(form, field):
    host_regex = r'^[a-zA-Z0-9_\.\-]+$'  # include _ for docker

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def S3UPLOAD__PORT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Port must be 0 or greater')

    if field.data > 65535:
        raise ValidationError('Port must be less than 65535')


def MQTTPUBLISH__BASE_TOPIC_validator(form, field):
    topic_regex = r'^[a-zA-Z0-9_\-\/]+$'

    if not re.search(topic_regex, field.data):
        raise ValidationError('Invalid characters in base topic')

    if re.search(r'^\/', field.data):
        raise ValidationError('Base topic cannot begin with slash')

    if re.search(r'\/$', field.data):
        raise ValidationError('Base topic cannot end with slash')


def MQTTPUBLISH__TOPIC_validator(form, field):
    if re.search(r'^\/', field.data):
        raise ValidationError('Topic cannot begin with slash')

    if re.search(r'\/$', field.data):
        raise ValidationError('Topic cannot end with slash')


def MQTTPUBLISH__QOS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data not in (0, 1, 2):
        raise ValidationError('Invalid QoS')


def SYNCAPI__BASEURL_validator(form, field):
    try:
        r = urlparse(field.data)
    except AttributeError:
        raise ValidationError('Invalid URL')

    if not r.scheme:
        raise ValidationError('Invalid URL')

    if r.scheme not in ('https',):
        raise ValidationError('URL should begin with https://')

    if re.search(r'\/$', field.data):
        raise ValidationError('URL cannot end with slash')

    if str(r.netloc) in ('localhost', '127.0.0.1', '[::1]', '::1'):
        raise ValidationError('Do not sync to localhost, bad things happen')


def ALLSKYMAP__API_URL_validator(form, field):
    if form.ALLSKYMAP__ENABLE.data and not field.data:
        raise ValidationError('API URL is required when Allsky Map integration is enabled')
    if field.data:
        try:
            r = urlparse(field.data)
            if not r.scheme or r.scheme not in ('http', 'https'):
                raise ValidationError('URL must start with http:// or https://')
        except Exception:
            raise ValidationError('Invalid URL')


def ALLSKYMAP__API_KEY_validator(form, field):
    if form.ALLSKYMAP__ENABLE.data and not field.data:
        raise ValidationError('API Key is required when Allsky Map integration is enabled')


def YOUTUBE__DESCRIPTION_TEMPLATE_validator(form, field):
    if not field.data:
        return

    now = datetime.now()

    template_data = {
        'day_date'   : now.date(),
        'timeofday'  : 'Night',
    }

    try:
        field.data.format(**template_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def TEMP_SENSOR__OPENWEATHERMAP_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__WUNDERGROUND_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__ASTROSPHERIC_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__AMBIENTWEATHER_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__ECOWITT_APIKEY_validator(form, field):
    pass


