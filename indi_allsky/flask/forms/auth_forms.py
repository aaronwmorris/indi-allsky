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

from .validators import *
from .config_form import IndiAllskyConfigForm


from .validators import *
from .config_form import IndiAllskyConfigForm

def LOGIN__USERNAME_validator(form, field):
    username_regex = r'^[a-zA-Z0-9\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


class IndiAllskyLoginForm(FlaskForm):
    USERNAME          = StringField('Username', validators=[DataRequired(), LOGIN__USERNAME_validator])
    PASSWORD          = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[DataRequired(), FILETRANSFER__PASSWORD_validator])
    NEXT              = HiddenField('Next')


def USER__NAME_validator(form, field):
    pass


def USER__EMAIL_validator(form, field):
    email_regex = r'[^@]+@[^@]+\.[^@]+'

    if not re.search(email_regex, field.data):
        raise ValidationError('Email address is not valid')


def USER__NEW_PASSWORD_validator(form, field):
    if not field.data:
        return

    if len(field.data) < 8:
        raise ValidationError('Password must be 8 characters or more')


class IndiAllskyUserInfoForm(FlaskForm):
    IDP_choices = (
        ('local', 'Local'),
        ('oidc', 'OIDC'),
    )

    USERNAME          = StringField('Username', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    NAME              = StringField('Name', validators=[DataRequired(), USER__NAME_validator])
    EMAIL             = StringField('Email', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    ADMIN             = BooleanField('Admin', render_kw={'disabled' : 'disabled'})
    IDP               = SelectField('Identity Provider', choices=IDP_choices, validators=[], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    CURRENT_PASSWORD  = PasswordField('Current Password', widget=PasswordInput(), validators=[], render_kw={'autocomplete' : 'new-password'})
    NEW_PASSWORD      = PasswordField('New Password', widget=PasswordInput(), validators=[USER__NEW_PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    NEW_PASSWORD2     = PasswordField('', widget=PasswordInput(), validators=[], render_kw={'autocomplete' : 'new-password'})


    def validate(self, user):
        result = super(IndiAllskyUserInfoForm, self).validate()

        if self.CURRENT_PASSWORD.data:
            if not argon2.verify(self.CURRENT_PASSWORD.data, user.password):
                self.CURRENT_PASSWORD.errors.append('Current password is not valid')
                result = False


        if self.NEW_PASSWORD.data != self.NEW_PASSWORD2.data:
            self.NEW_PASSWORD2.errors.append('Passwords do not match')
            result = False


        if argon2.verify(self.NEW_PASSWORD.data, user.password):
            self.NEW_PASSWORD.errors.append('Password cannot be the same as the old password')
            result = False

        return result


