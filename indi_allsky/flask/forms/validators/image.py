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


def IMAGE_COLORMAP_validator(form, field):
    if field.data not in list(zip(*form.IMAGE_COLORMAP_choices))[0]:
        raise ValidationError('Please select a valid colormap')


def WB_FACTOR_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Balance factor must be 0 or greater')

    if field.data > 4.0:
        raise ValidationError('Balance factor must be less than 4.0')


def WB_MTF_MIDTONES_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Value must be 0.0 or more')

    if field.data > 1.0:
        raise ValidationError('Value must be 1.0 or less')


def SATURATION_FACTOR_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Saturation factor must be 0 or greater')

    if field.data > 4.0:
        raise ValidationError('Saturation factor must be less than 4.0')


def GAMMA_CORRECTION_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Gamma most be greater than 0')


def SHARPEN_AMOUNT_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Sharpen amount must be 0 or greater')

    if field.data > 2.0:
        raise ValidationError('Sharpen amount must be 2.0 or less')


def SCNR_ALGORITHM_validator(form, field):
    if field.data not in list(zip(*form.SCNR_ALGORITHM_choices))[0]:
        raise ValidationError('Please select a valid algorithm')


def SCNR_MTF_MIDTONES_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.5:
        raise ValidationError('Value must be 0.5 or more')

    if field.data > 1.0:
        raise ValidationError('Value must be 1.0 or less')


def IMAGE_DENOISE_validator(form, field):
    if field.data not in list(zip(*form.IMAGE_DENOISE_choices))[0]:
        raise ValidationError('Please select a valid denoise algorithm')


def IMAGE_DENOISE_STRENGTH_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Strength must be 1 or more')

    if field.data > 5:
        raise ValidationError('Strength must be 5 or less')


def BILATERAL_SIGMA_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Sigma must be 1 or more')

    if field.data > 50:
        raise ValidationError('Sigma must be 50 or less')


def IMAGE_CALIBRATE_HOLE_THOLD_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Threshold must be greater than 0')

    if field.data > 100:
        raise ValidationError('Threshold must be less than 100')


def IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(form, field):
    """Keep detector ratios finite, positive, and operationally bounded."""
    if not isinstance(field.data, (int, float)) or not math.isfinite(field.data):
        raise ValidationError('Enter a number, or restore the default shown below')

    if field.data <= 0:
        raise ValidationError('Enter a value greater than 0, or restore the default')

    if field.data > asi676mc.RATIO_THRESHOLD_MAX:
        raise ValidationError(
            'Enter a value no greater than {0:g}, or restore the default'.format(
                asi676mc.RATIO_THRESHOLD_MAX,
            )
        )


def IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(form, field):
    """Preserve Bayer parity while bounding detector sampling work."""
    if not isinstance(field.data, int):
        raise ValidationError('Enter a whole number, or restore the default')

    if field.data < 2 or field.data > asi676mc.SAMPLE_STEP_MAX or field.data % 2:
        raise ValidationError(
            'Enter an even number between 2 and {0:d}, or restore the default'.format(
                asi676mc.SAMPLE_STEP_MAX,
            )
        )


def IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator(form, field):
    """Restrict the clipping plateau to the unsigned RAW16 range."""
    if not isinstance(field.data, int):
        raise ValidationError('Enter a whole number, or restore the default')

    if field.data < 1 or field.data > 65535:
        raise ValidationError('Enter a value between 1 and 65535, or restore the default')


def IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(form, field):
    """Require one finite normalized highlight transition ratio."""
    if not isinstance(field.data, (int, float)) or not math.isfinite(field.data):
        raise ValidationError('Enter a number, or restore the default shown below')

    if field.data <= 0 or field.data > 1:
        raise ValidationError('Enter a value greater than 0 and no more than 1, or restore the default')


def IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator(form, field):
    """Require an ordered highlight transition representable at runtime."""
    IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(form, field)

    start_ratio = form.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO.data
    if isinstance(start_ratio, (int, float)) and field.data <= start_ratio:
        raise ValidationError('Enter an end value greater than the start value, or restore both defaults')
    if isinstance(start_ratio, (int, float)):
        try:
            asi676mc.normalize_settings({
                'HIGHLIGHT_BLEND_START_RATIO': start_ratio,
                'HIGHLIGHT_BLEND_END_RATIO': field.data,
            })
        except ValueError as error:
            raise ValidationError(str(error)) from error


def IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(form, field):
    """Preserve Bayer parity while bounding repair working memory."""
    if not isinstance(field.data, int):
        raise ValidationError('Enter a whole number, or restore the default')

    if field.data < 2 or field.data > asi676mc.CHUNK_ROWS_MAX or field.data % 2:
        raise ValidationError(
            'Enter an even number between 2 and {0:d}, or restore the default'.format(
                asi676mc.CHUNK_ROWS_MAX,
            )
        )


def CLAHE_GRIDSIZE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 4:
        raise ValidationError('Grid size must be 4 or greater')

    if field.data > 64:
        raise ValidationError('Clip limit must be 64 or less')


def IMAGE_LABEL_SYSTEM_validator(form, field):
    if not field.data:
        return

    if field.data not in ['opencv', 'pillow']:
        raise ValidationError('Unknown label system')


def WEB_EXTRA_TEXT_validator(form, field):
    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')


    web_extra_text_p = Path(field.data)

    try:
        if not web_extra_text_p.exists():
            raise ValidationError('File does not exist')

        if not web_extra_text_p.is_file():
            raise ValidationError('Not a file')

        # Sanity check
        if web_extra_text_p.stat().st_size > 10000:
            raise ValidationError('File is too large')

        with io.open(str(web_extra_text_p), 'r', encoding='utf-8'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def IMAGE_STRETCH__CLASSNAME_validator(form, field):
    if not field.data:
        return

    class_regex = r'^[a-zA-Z0-9_\-]+$'

    if not re.search(class_regex, field.data):
        raise ValidationError('Invalid class syntax')


def IMAGE_STRETCH__MODE1_GAMMA_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Gamma must be 0 or greater')


def IMAGE_STRETCH__MODE1_STDDEVS_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Standard deviations must be 1.0 or greater')


def IMAGE_STRETCH__MODE2_SHADOWS_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0.0 or greater')

    if field.data > 0.5:
        raise ValidationError('Value must be 0.5 or less')


def IMAGE_STRETCH__MODE2_MIDTONES_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0.0 or greater')

    if field.data > 1:
        raise ValidationError('Value must be 1.0 or less')


def IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.5:
        raise ValidationError('Value must be 0.5 or greater')

    if field.data > 1:
        raise ValidationError('Value must be 1.0 or less')


def IMAGE_STRETCH__MODE3_SHADOWS_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0.0 or greater')

    if field.data > 0.5:
        raise ValidationError('Value must be 0.5 or less')


def IMAGE_STRETCH__MODE3_MIDTONES_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0.0 or greater')

    if field.data > 1:
        raise ValidationError('Value must be 1.0 or less')


def IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.5:
        raise ValidationError('Value must be 0.5 or greater')

    if field.data > 1:
        raise ValidationError('Value must be 1.0 or less')


def IMAGE_ROTATE_validator(form, field):
    import cv2

    if not field.data:
        return

    if field.data not in ['ROTATE_90_CLOCKWISE', 'ROTATE_90_COUNTERCLOCKWISE', 'ROTATE_180']:
        raise ValidationError('Unknown rotation option')

    # sanity check
    try:
        getattr(cv2, field.data)
    except AttributeError as e:
        raise ValidationError(str(e))


def IMAGE_ROTATE_ANGLE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


    if field.data < -180:
        raise ValidationError('Rotation angle must be -180 or greater')

    if field.data > 180:
        raise ValidationError('Rotation angle must be 180 or less')


def IMAGE_EXTRA_TEXT_validator(form, field):
    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')


    image_extra_text_p = Path(field.data)

    try:
        if not image_extra_text_p.exists():
            raise ValidationError('File does not exist')

        if not image_extra_text_p.is_file():
            raise ValidationError('Not a file')

        # Sanity check
        if image_extra_text_p.stat().st_size > 10000:
            raise ValidationError('File is too large')

        with io.open(str(image_extra_text_p), 'r', encoding='utf-8'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


def FISH2PANO__ROTATE_ANGLE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -180:
        raise ValidationError('Rotation angle must be -180 or greater')

    if field.data > 180:
        raise ValidationError('Rotation angle must be 180 or less')


def TEXT_PROPERTIES__FONT_FACE_validator(form, field):
    fonts = (
        'FONT_HERSHEY_SIMPLEX',
        'FONT_HERSHEY_PLAIN',
        'FONT_HERSHEY_DUPLEX',
        'FONT_HERSHEY_COMPLEX',
        'FONT_HERSHEY_TRIPLEX',
        'FONT_HERSHEY_COMPLEX_SMALL',
        'FONT_HERSHEY_SCRIPT_SIMPLEX',
        'FONT_HERSHEY_SCRIPT_COMPLEX',
    )

    if field.data not in fonts:
        raise ValidationError('Invalid selection')


def TEXT_PROPERTIES__FONT_HEIGHT_validator(form, field):
    if field.data < 1:
        raise ValidationError('Font height must be greater than 1')


def TEXT_PROPERTIES__FONT_X_validator(form, field):
    if field.data < 1:
        raise ValidationError('Font offset must be greater than 1')


def TEXT_PROPERTIES__FONT_Y_validator(form, field):
    if field.data < 1:
        raise ValidationError('Font offset must be greater than 1')


def TEXT_PROPERTIES__PIL_FONT_FILE_validator(form, field):
    if field.data not in list(zip(*form.TEXT_PROPERTIES__PIL_FONT_FILE_choices))[0]:
        raise ValidationError('Invalid font selection')


def TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(form, field):
    from PIL import ImageFont

    if not field.data:
        return

    font_file_p = Path(field.data)

    try:
        if not font_file_p.exists():
            raise ValidationError('File does not exist')

        if not font_file_p.is_file():
            raise ValidationError('Path is not a file')

        if not os.access(str(font_file_p), os.R_OK):
            raise ValidationError('Font is not readable')
    except PermissionError as e:
        raise ValidationError(str(e))


    try:
        ImageFont.truetype(str(font_file_p), 30)
    except OSError as e:
        raise ValidationError(str(e))


def TEXT_PROPERTIES__PIL_FONT_SIZE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 10:
        raise ValidationError('Size must be 10 or greater')


def LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Border must be 0 or more')

    if field.data > 10:
        raise ValidationError('Border must 10 or less')


def TEXT_PROPERTIES__FONT_SCALE_validator(form, field):
    if field.data < 0.1:
        raise ValidationError('Font scale must be greater than 0.1')

    if field.data > 100:
        raise ValidationError('Font scale too large')


def TEXT_PROPERTIES__FONT_THICKNESS_validator(form, field):
    if field.data < 1:
        raise ValidationError('Font thickness must be 1 or more')

    if field.data > 20:
        raise ValidationError('Font thickness must be less than 20')


def IMAGE_BORDER_SIDE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Border must be 0 or greater')

    if field.data > 1000:
        raise ValidationError('Border must be less than 1000')


def ADSB__LABEL_LIMIT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 1:
        raise ValidationError('Limit must be greater than 0')

    if field.data > 20:
        raise ValidationError('Limit must be 20 or less')


def SATELLITE_TRACK__LABEL_LIMIT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 1:
        raise ValidationError('Limit must be greater than 0')

    if field.data > 20:
        raise ValidationError('Limit must be 20 or less')


