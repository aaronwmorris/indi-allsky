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


def HOOK_TIMEOUT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Timeout must be greater than 0')

    if field.data > 20:
        raise ValidationError('Timeout must be less than 20')


def DEW_HEATER__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.DEW_HEATER__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def DEW_HEATER__LEVEL_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 0:
        raise ValidationError('Level must be 0 or greater')

    if field.data > 100:
        raise ValidationError('Level must be 100 or less')


def DEW_HEATER__THOLD_DIFF_validator(form, field):
    try:
        int(field.data)
    except ValueError:
        raise ValidationError('Please enter a valid number')


def DEW_HEATER__MANUAL_TARGET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def DEW_HEATER__HOLD_SECONDS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 0:
        raise ValidationError('Must be 0 or greater')

    if field.data > 600:
        raise ValidationError('Must be 600 or less')


def FAN__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.FAN__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def FAN__LEVEL_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 0:
        raise ValidationError('Level must be 0 or greater')

    if field.data > 100:
        raise ValidationError('Level must be 100 or less')


def FAN__THOLD_DIFF_validator(form, field):
    try:
        int(field.data)
    except ValueError:
        raise ValidationError('Please enter a valid number')


def FAN__HOLD_SECONDS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 0:
        raise ValidationError('Must be 0 or greater')

    if field.data > 600:
        raise ValidationError('Must be 600 or less')


def FAN__TARGET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def GENERIC_GPIO__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.GENERIC_GPIO__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def MANUAL_GPIO__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.MANUAL_GPIO__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def SENSOR_SLOT_validator(form, field):
    slots = list()
    for v in form.SENSOR_SLOT_choices.values():
        slots.extend(list(zip(*v))[0])

    if field.data not in slots:
        raise ValidationError('Invalid selection')


def SENSOR_USER_VAR_SLOT_validator(form, field):
    if field.data not in list(zip(*form.SENSOR_USER_VAR_SLOT_choices))[0]:
        raise ValidationError('Invalid selection')


