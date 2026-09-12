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


def TIMELAPSE__PRE_PROCESSOR_validator(form, field):
    if field.data not in list(zip(*form.TIMELAPSE__PRE_PROCESSOR_choices))[0]:
        raise ValidationError('Invalid selection')


def TIMELAPSE__KEOGRAM_RATIO_validator(form, field):
    if not isinstance(field.data, float):
        raise ValidationError('Please enter valid number')

    if field.data < 0.01:
        raise ValidationError('Ratio must be 0.01 or greater')

    if field.data > 0.33:
        raise ValidationError('Ratio must be 0.33 or less')


def TIMELAPSE__PRE_SCALE_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Pre-Scaling factor must be greater than 0')

    if field.data > 100:
        raise ValidationError('Pre-Scaling factor must be 100 or less')


def KEOGRAM_ANGLE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -180:
        raise ValidationError('Rotation angle must be -180 or greater')

    if field.data > 180:
        raise ValidationError('Rotation angle must be 180 or less')


def KEOGRAM_H_SCALE_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Keogram Horizontal Scaling factor must be greater than 0')

    if field.data > 100:
        raise ValidationError('Keogram Horizontal Scaling factor must be 100 or less')


def KEOGRAM_V_SCALE_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Keogram Verticle Scaling factor must be greater than 0')

    if field.data > 100:
        raise ValidationError('Keogram Verticle Scaling factor must be 100 or less')


def KEOGRAM_CROP_TOP_validator(form, field):
    if field.data < 0:
        raise ValidationError('Keogram Crop percent must be 0 or greater')

    if field.data > 49:
        raise ValidationError('Keogram crop percent must be 49 or less')


def KEOGRAM_CROP_BOTTOM_validator(*args):
    KEOGRAM_CROP_TOP_validator(*args)


def LONGTERM_KEOGRAM__OFFSET_X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def LONGTERM_KEOGRAM__OFFSET_Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def REALTIME_KEOGRAM__MAX_ENTRIES_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


    if field.data < 0:
        raise ValidationError('Entries must be 0 or greater')

    if field.data > 10000:
        raise ValidationError('Entries must be 5000 or less')


def REALTIME_KEOGRAM__SAVE_INTERVAL_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


    if field.data < 1:
        raise ValidationError('Entries must be 1 or greater')

    if field.data > 100:
        raise ValidationError('Entries must be 100 or less')


def IMAGE_SCALE_validator(form, field):
    if field.data < 1:
        raise ValidationError('Image Scaling must be 1 or greater')

    if field.data > 100:
        raise ValidationError('Image Scaling must be 100 or less')


def FISH2PANO__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.1:
        raise ValidationError('Scale must be 0.1 or greater')

    if field.data > 1.0:
        raise ValidationError('Scale must be 1.0 or less')


def IMAGE_CROP_ROI_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Crop Region of Interest must be 0 or greater')


def TIMELAPSE_EXPIRE_DAYS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Timelapse Expiration must be 1 or greater')


def FFMPEG_VFSCALE_validator(form, field):
    if not field.data:
        return

    scale_regex = r'^[a-z0-9\-\*\.]+\:[a-z0-9\-\*\.]+$'
    if not re.search(scale_regex, field.data):
        raise ValidationError('Invalid scale option')


def FFMPEG_CODEC_validator(form, field):
    if field.data not in list(zip(*form.FFMPEG_CODEC_choices))[0]:
        raise ValidationError('Invalid codec option')


def MOON_OVERLAY__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.1:
        raise ValidationError('Image scale must be 0.1 or more')

    if field.data > 2.0:
        raise ValidationError('Image scale must be 2.0 or less')


def LIGHTGRAPH_OVERLAY__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Must be greater than 0')

    if field.data > 1.0:
        raise ValidationError('Must be 1.0 or less')


