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


def WEBSITE__TITLE_validator(form, field):
    pass


def OWNER_validator(form, field):
    if not field.data:
        return

    owner_regex = r'^[a-zA-Z0-9\_\.\ \-\@]+$'

    if not re.search(owner_regex, field.data):
        raise ValidationError('Invalid characters in owner name')


def PRESSURE_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.PRESSURE_DISPLAY_choices))[0]:
        raise ValidationError('Please select the pressure system for display')


def WINDSPEED_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.WINDSPEED_DISPLAY_choices))[0]:
        raise ValidationError('Please select the wind speed system for display')


def DETECT_METEORS_THOLD_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data <= 10:
        raise ValidationError('Threshold must be greater than 10')

    if field.data > 1000:
        raise ValidationError('Threshold must be 1000 or less')


def IMAGE_QUEUE_MAX_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 2:
        raise ValidationError('Queue max size must be 2 or greater')


def IMAGE_QUEUE_MIN_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Queue min size must be 1 or greater')


def IMAGE_QUEUE_BACKOFF_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Backoff multiplier must be greater than 0')


def IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in list(zip(*form.IMAGE_FILE_TYPE_choices))[0]:
        raise ValidationError('Please select a valid file type')


def IMAGE_SAVE_FITS_PERIOD_validator(form, field):
    if field.data not in list(zip(*form.IMAGE_SAVE_FITS_PERIOD_choices))[0]:
        raise ValidationError('Invalid codec option')


def IMAGE_FILE_COMPRESSION__JPG_validator(form, field):
    if field.data < 1:
        raise ValidationError('JPEG compression must be 1 or greater')

    if field.data > 100:
        raise ValidationError('JPEG compression must be 100 or less')


def IMAGE_FILE_COMPRESSION__PNG_validator(form, field):
    if field.data < 1:
        raise ValidationError('PNG compression must be 1 or greater')

    if field.data > 9:
        raise ValidationError('PNG compression must be 9 or less')


def VARLIB_FOLDER_validator(form, field):
    folder_regex = r'[^a-zA-Z0-9_\.\-\/]'

    m = re.findall(folder_regex, field.data)
    if m:
        raise ValidationError('Folder contains disallowed characters: {0:s}'.format(', '.join(set(m))))

    if re.search(r'\/$', field.data):
        raise ValidationError('Directory cannot end with slash')


    varlib_folder_p = Path(field.data)

    try:
        if not varlib_folder_p.is_dir():
            if varlib_folder_p.exists():
                # folder path exists, but is not a directory
                raise ValidationError('Path is not a directory')

            raise ValidationError('Folder does not exist')


        if not os.access(str(varlib_folder_p), os.R_OK):
            raise ValidationError('Folder not readable')

        if not os.access(str(varlib_folder_p), os.W_OK):
            raise ValidationError('Folder not writable')

        if not os.access(str(varlib_folder_p), os.X_OK):
            raise ValidationError('Folder not accessible')

    except PermissionError as e:
        raise ValidationError(str(e))
    except OSError as e:
        raise ValidationError(str(e))


def IMAGE_FOLDER_validator(form, field):
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


def LOGO_OVERLAY_validator(form, field):
    import cv2

    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'
    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')

    ext_regex = r'\.png$'
    if not re.search(ext_regex, field.data, re.IGNORECASE):
        raise ValidationError('Mask file must be a PNG')

    overlay_p = Path(field.data)

    try:
        if not overlay_p.exists():
            raise ValidationError('File does not exist')

        if not overlay_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(overlay_p), 'rb'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


    mask_data = cv2.imread(str(overlay_p), cv2.IMREAD_UNCHANGED)
    if isinstance(mask_data, type(None)):
        raise ValidationError('File is not a valid image')

    try:
        if mask_data.shape[2] != 4:
            raise ValidationError('Mask does not contain an alpha channel')
    except IndexError:
        raise ValidationError('Mask does not contain an alpha channel')


def IMAGE_CALIBRATE_MANUAL_OFFSET_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Offset must be 0 or more')


def FISH2PANO__DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 100:
        raise ValidationError('Diameter must be 100 or greater')


def FISH2PANO__OFFSET_X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def FISH2PANO__OFFSET_Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def FISH2PANO__MODULUS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Modulus must be 1 or greater')


def IMAGE_STACK_METHOD_validator(form, field):
    stack_methods = (
        'maximum',
        'average',
        'minimum',
    )

    if field.data not in stack_methods:
        raise ValidationError('Invalid selection')


def IMAGE_STACK_COUNT_validator(form, field):
    try:
        stack_count = int(field.data)
    except ValueError:
        raise ValidationError('Invalid data')

    if stack_count < 1:
        raise ValidationError('Stack count too low')


def IMAGE_ALIGN_DETECTSIGMA_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 2:
        raise ValidationError('Detection Sigma must be 3 or greater')

    if field.data > 20:
        raise ValidationError('Detection Sigma must be 20 or less')


def IMAGE_ALIGN_POINTS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 25:
        raise ValidationError('Detection points must be 25 or greater')

    if field.data > 200:
        raise ValidationError('Detection points must be 200 or less')


def IMAGE_ALIGN_SOURCEMINAREA_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 3:
        raise ValidationError('Source min area must be 3 or greater')

    if field.data > 25:
        raise ValidationError('Source min area must be 25 or less')


def IMAGE_EXPIRE_DAYS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Image Expiration must be 1 or greater')


def FFMPEG_FRAMERATE_validator(form, field):
    # guessing
    if field.data < 10:
        raise ValidationError('FFMPEG frame rate must be 10 or greater')

    if field.data > 60:
        raise ValidationError('FFMPEG frame rate must be 60 or less')


def FFMPEG_BITRATE_validator(form, field):
    bitrate_regex = r'^\d+[km]$'

    if not re.search(bitrate_regex, field.data):
        raise ValidationError('Invalid bitrate syntax')


def FFMPEG_EXTRA_OPTIONS_validator(form, field):
    if not field.data:
        return

    options_regex = r'^[a-zA-Z0-9_\.\,\-\:\;\/\ \=\'\*\[\]\(\)]+$'
    if not re.search(options_regex, field.data):
        raise ValidationError('Invalid characters')

    begin_space_regex = r'^\ '
    if re.search(begin_space_regex, field.data):
        raise ValidationError('Options cannot begin with a space')

    end_space_regex = r'\ $'
    if re.search(end_space_regex, field.data):
        raise ValidationError('Options cannot end with a space')

    multi_space_regex = r'\ \ '
    if re.search(multi_space_regex, field.data):
        raise ValidationError('Options cannot contain multiple concurrent space characters')


def MOON_OVERLAY__X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def MOON_OVERLAY__Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 10:
        raise ValidationError('Height must be 10 or more')

    if field.data > 100:
        raise ValidationError('Height must 100 or less')


def LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 3:
        raise ValidationError('Must be 3 or more')

    if field.data > 20:
        raise ValidationError('Must 20 or less')


def LIGHTGRAPH_OVERLAY__OPACITY_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Opacity must be 0 or more')


    if field.data > 100:
        raise ValidationError('Opacity must be 100 or less')


def LIGHTGRAPH_OVERLAY__OFFSET_X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def LIGHTGRAPH_OVERLAY__Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def LIGHTGRAPH_OVERLAY__RGB_COLOR_validator(form, field):
    color_regex = r'^\d+\,\d+\,\d+$'

    if not re.search(color_regex, field.data):
        raise ValidationError('Invalid syntax')

    rgb = field.data.split(',')
    for c in rgb:
        if int(c) < 0:
            raise ValidationError('Invalid syntax')
        elif int(c) > 255:
            raise ValidationError('Invalid syntax')

    if sum([int(c) for c in rgb]) == 0:
        raise ValidationError('Color cannot be (0, 0, 0)')


def IMAGE_OVERLAY__URL_validator(form, field):
    if not field.data:
        return

    try:
        r = urlparse(field.data)
    except AttributeError:
        raise ValidationError('Invalid URL')

    if not r.scheme:
        raise ValidationError('Invalid URL')


def IMAGE_OVERLAY__LOAD_INTERVAL_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 60:
        raise ValidationError('Must be 60 or more')


def IMAGE_OVERLAY__W_H_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 10:
        raise ValidationError('Must be 10 or more')


def IMAGE_OVERLAY__X_Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def IMAGE_OVERLAY__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in list(zip(*form.IMAGE_OVERLAY__IMAGE_FILE_TYPE_choices))[0]:
        raise ValidationError('Please select a valid file type')


def CARDINAL_DIRS__CHAR_validator(form, field):
    if not field.data:
        return

    if len(field.data) != 1:
        raise ValidationError('String must be one character')


def CARDINAL_DIRS__DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 100:
        raise ValidationError('Diameter must be 100 or greater')


def CARDINAL_DIRS__CENTER_OFFSET_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def CARDINAL_DIRS__SIDE_OFFSET_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < -20:
        raise ValidationError('Offset must be greater than -20')

    if field.data > 300:
        raise ValidationError('Offset must be less than 300')


def RGB_COLOR_validator(form, field):
    color_regex = r'^\d+\,\d+\,\d+$'

    if not re.search(color_regex, field.data):
        raise ValidationError('Invalid syntax')

    rgb = field.data.split(',')
    for c in rgb:
        if int(c) < 0:
            raise ValidationError('Invalid syntax')
        elif int(c) > 255:
            raise ValidationError('Invalid syntax')


def ORB_PROPERTIES__MODE_validator(form, field):
    if field.data not in ('ha', 'az', 'alt', 'off'):
        raise ValidationError('Please select a valid orb mode')


def ORB_PROPERTIES__RADIUS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Orb radius must be 1 or more')


def ORB_PROPERTIES__AZ_OFFSET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -180:
        raise ValidationError('Azimuth Offset must be greater than -180')

    if field.data > 180:
        raise ValidationError('Azimuth Offset must be less than 180')


def ADSB__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\ \@\.\-\\]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def ADSB__DUMP1090_URL_validator(form, field):
    if not field.data:
        return

    try:
        r = urlparse(field.data)
    except AttributeError:
        raise ValidationError('Invalid URL')

    if not r.scheme:
        raise ValidationError('Invalid URL')


def ADSB__PASSWORD_validator(form, field):
    pass


def ALLSKYMAP__INTERVAL_validator(form, field):
    if field.data is not None:
        try:
            val = int(field.data)
            if val < 1:
                raise ValidationError('Interval must be at least 1 minute')
        except ValueError:
            raise ValidationError('Please enter a valid number')


def FITSHEADER_KEY_validator(form, field):
    header_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(header_regex, field.data):
        raise ValidationError('Invalid characters in header')

    if len(field.data) > 8:
        raise ValidationError('Header must be 8 characters or less')


def VIRTUALSKY__MAGNITUDE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def VIRTUALSKY__OFFSET_X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


def VIRTUALSKY__OFFSET_Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


def CIRCULAR_DISPLAY__RESOLUTION_validator(form, field):
    if field.data not in list(zip(*form.CIRCULAR_DISPLAY__RESOLUTION_choices))[0]:
        raise ValidationError('Invalid selection')


def PWM_FREQUENCY_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 1:
        raise ValidationError('Must be 1 or greater')

    if field.data > 10000:
        raise ValidationError('Must be 10000 or less')


def I2C_ADDRESS_validator(form, field):
    try:
        address = int(field.data, 16)
    except ValueError as e:
        raise ValidationError('Invalid I2C address: {0:s}'.format(str(e)))


    if address < 0:
        raise ValidationError('I2C address must be greater than 0x00')
    elif address > 127:
        raise ValidationError('I2C address must be 0x7f or less')


def CUSTOM_CHART_validator(form, field):
    slots = list()
    for v in form.CUSTOM_CHART_choices.values():
        slots.extend(list(zip(*v))[0])

    for v in form.SENSOR_SLOT_choices.values():
        slots.extend(list(zip(*v))[0])


    if field.data not in slots:
        raise ValidationError('Invalid selection')


def CUSTOM_CHART_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def DEVICE_PIN_NAME_validator(form, field):
    if not field.data:
        return


    class_regex = r'^[a-zA-Z0-9_,\-\/]+$'

    if not re.search(class_regex, field.data):
        raise ValidationError('Invalid PIN name')


def HEALTHCHECK__DISK_USAGE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


    if field.data < 0:
        raise ValidationError('Percentage must be 0 or greater')

    if field.data > 101:
        raise ValidationError('Percentage must be 101 or less')


def HEALTHCHECK__SWAP_USAGE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


    if field.data < 0:
        raise ValidationError('Percentage must be 0 or greater')

    if field.data > 101:
        raise ValidationError('Percentage must be 101 or less')


def ADSB__ALT_DEG_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 5:
        raise ValidationError('Minimum altitude must be greater than 5')

    if field.data > 90:
        raise ValidationError('Minimum altitude must be less than 90')


def SATELLITE_TRACK__ALT_DEG_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Minimum altitude must be 0 or more')

    if field.data > 90:
        raise ValidationError('Minimum altitude must be less than 90')


def INDI_CONFIG_DEFAULTS_validator(form, field):
    try:
        json_data = json.loads(field.data)
    except json.decoder.JSONDecodeError as e:
        raise ValidationError(str(e))


    for k in json_data.keys():
        if k.startswith('#'):
            # comment
            continue

        if k not in ('PROPERTIES', 'TEXT', 'SWITCHES'):
            raise ValidationError('Only PROPERTIES, TEXT, and SWITCHES attributes allowed')


    for k, v in json_data.get('PROPERTIES', {}).items():
        if not isinstance(v, dict):
            raise ValidationError('Number property {0:s} value must be a dict'.format(k))

        for k2 in v.keys():
            if k2.startswith('#'):
                # comment
                continue

    for k, v in json_data.get('TEXT', {}).items():
        if not isinstance(v, dict):
            raise ValidationError('Text property {0:s} value must be a dict'.format(k))

        for k2 in v.keys():
            if k2.startswith('#'):
                # comment
                continue

    for k, v in json_data.get('SWITCHES', {}).items():
        if not isinstance(v, dict):
            raise ValidationError('Switch {0:s} value must be a dict'.format(k))

        for k2 in v.keys():
            if k2.startswith('#'):
                # comment
                continue

            if k2 not in ('on', 'off'):
                raise ValidationError('Invalid switch configuration {0:s}'.format(k2))

            if not isinstance(v[k2], list):
                raise ValidationError('Switch {0:s} "{1:s}" value must be a list'.format(k, k2))


def INDI_CONFIG_DAY_validator(*args):
    INDI_CONFIG_DEFAULTS_validator(*args)


