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


def LENS_NAME_validator(form, field):
    if not field.data:
        return


def LENS_FOCAL_LENGTH_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Focal length must be greater than 0')


def LENS_FOCAL_RATIO_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Focal ratio must be greater than 0')


def LENS_IMAGE_CIRCLE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Focal ratio must be greater than 0')


def LENS_OFFSET_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def LENS_ALTITUDE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Altitude must be 0 or greater')

    if field.data > 90.0:
        raise ValidationError('Altitude must be 90 or less')


def LENS_AZIMUTH_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Azimuth must be 0 or greater')

    if field.data > 360.0:
        raise ValidationError('Azimuth must be 360 or less')


def TIMELAPSE__IMAGE_CIRCLE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 100:
        raise ValidationError('Diameter must be 100 or greater')


def ADU_FOV_DIV_validator(form, field):
    if int(field.data) not in (2, 3, 4, 6):
        raise ValidationError('ADU FoV divisor must be 2, 3, 4, 5, or 6')


def SQM_FOV_DIV_validator(form, field):
    if int(field.data) not in (2, 3, 4, 6):
        raise ValidationError('SQM FoV divisor must be 2, 3, 4, 5, or 6')


def DETECT_STARS_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Threshold must be greater than 0')

    if field.data > 1.0:
        raise ValidationError('Threshold must be 1.0 or less')


def DETECT_STARS_SEP_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.5:
        raise ValidationError('Sigma must be 0.5 or greater')

    if field.data > 50.0:
        raise ValidationError('Sigma must be 50.0 or less')


def DETECT_STARS_SEP_MAX_RADIUS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Max radius must be 1 or greater')

    if field.data > 500:
        raise ValidationError('Max radius must be 500 or less')


def LOCATION_NAME_validator(form, field):
    if not field.data:
        return


def LOCATION_LATITUDE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -90:
        raise ValidationError('Latitude must be greater than -90')

    if field.data > 90:
        raise ValidationError('Latitude must be less than 90')


def LOCATION_LONGITUDE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -180:
        raise ValidationError('Longitude must be greater than -180')

    if field.data > 180:
        raise ValidationError('Longitude must be less than 180')


def LOCATION_ELEVATION_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def NIGHT_SUN_ALT_DEG_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -90:
        raise ValidationError('Sun altitude must be greater than -90')

    if field.data > 90:
        raise ValidationError('Sun altitude must be less than 90')


def NIGHT_MOONMODE_ALT_DEG_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -90:
        raise ValidationError('Moon altitude must be greater than -90')

    # 91 is disabled
    if field.data > 91:
        raise ValidationError('Moon altitude must be less than 90')


def NIGHT_MOONMODE_PHASE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Moon illumination must be 0 or greater')

    if field.data > 100:
        raise ValidationError('Moon illumination must be 100 or less')


def STARTRAILS_MAX_ADU_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Star Trails Max ADU must be greater than 0')

    if field.data > 255:
        raise ValidationError('Star Trails Max ADU must be 255 or less')


def STARTRAILS_MASK_THOLD_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Star Trails Mask Threshold must be greater than 0')

    if field.data > 255:
        raise ValidationError('Star Trails Mask Threshold must be 255 or less')


def STARTRAILS_PIXEL_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Star Trails Pixel Threshold must be 0 or greater')

    if field.data > 100:
        raise ValidationError('Star Trails Pixel Threshold must be 100 or less')


def STARTRAILS_MIN_STARS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Minimum stars must be greater than 0')


def STARTRAILS_TIMELAPSE_MINFRAMES_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 25:
        raise ValidationError('Star Trails Timelapse Minimum Frames must be 25 or more')


def STARTRAILS_SUN_ALT_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -90:
        raise ValidationError('Sun altitude must be greater than -90')

    if field.data > 90:
        raise ValidationError('Sun altitude must be less than 90')


def STARTRAILS_MOON_ALT_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -90:
        raise ValidationError('Moon altitude must be greater than -90')

    if field.data > 91:
        raise ValidationError('Moon altitude must be less than 91')


def STARTRAILS_MOON_PHASE_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Moon phase must be greater than 0')

    if field.data > 101:
        raise ValidationError('Moon phase must be less than 101')


def IMAGE_CIRCLE_MASK__DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 100:
        raise ValidationError('Diameter must be 100 or greater')


def IMAGE_CIRCLE_MASK__OFFSET_X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def IMAGE_CIRCLE_MASK__OFFSET_Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def IMAGE_CIRCLE_MASK__BLUR_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Blur must be 0 or more')

    if field.data == 0:
        # 0 is disabled, but technically an even number
        pass
    elif field.data % 2 == 0:
        raise ValidationError('Blur must be an odd number')


def IMAGE_CIRCLE_MASK__OPACITY_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Opacity must be 0 or more')


    if field.data > 100:
        raise ValidationError('Opacity must be 100 or less')


def TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 0:
        raise ValidationError('Image Circle must be 0 or greater')


def TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


def TEST_CAMERA__ROTATING_STAR_COUNT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 100:
        raise ValidationError('Count must be 100 or greater')


def TEST_CAMERA__ROTATING_STAR_FACTOR_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Factor must be greater than 0')


def VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0 or greater')


def VIRTUALSKY__LATITUDE_OFFSET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def VIRTUALSKY__LONGITUDE_OFFSET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 100:
        raise ValidationError('Value must be 100 or greater')


