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


def CAMERA_INTERFACE_validator(form, field):
    interfaces = list()
    for v in form.CAMERA_INTERFACE_choices.values():
        interfaces.extend(list(zip(*v))[0])

    if field.data not in interfaces:
        raise ValidationError('Invalid camera interface')


def INDI_CAMERA_NAME_validator(form, field):
    if not field.data:
        return


def CCD_GAIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Gain must be 0 or higher')


def CCD_BINNING_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Bin mode must be more than 0')

    if field.data > 4:
        raise ValidationError('Bin mode must be less than 4')


def CCD_EXPOSURE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Default Exposure must be 0 or more')

    if field.data > 120.0:
        raise ValidationError('Default Exposure cannot be more than 120')


def CAMERA_SQM__EXPOSURE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('SQM Exposure must be 1.0 or greater')

    if field.data > 60.0:
        raise ValidationError('SQM Exposure must be 60.0 or less')


def CCD_EXPOSURE_TIMEOUT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 120:
        raise ValidationError('Timeout must be 120 or more')


def EXPOSURE_PERIOD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Exposure period must be 1.0 or more')


def EXPOSURE_PERIOD_DAY_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Exposure period must be 1.0 or more')


def CAMERA_SQM__EXPOSURE_PERIOD_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 60:
        raise ValidationError('Value must be 120 or more')


def SQM_MAGNITUDE_OFFSET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Value must be 0 or more')


def CCD_CONFIG__EXPOSURE_CLASSNAME_validator(form, field):
    exposure_classes = list()
    for v in form.CCD_CONFIG__EXPOSURE_CLASSNAME_choices.values():
        exposure_classes.extend(list(zip(*v))[0])

    if field.data not in exposure_classes:
        raise ValidationError('Invalid selection')


def CCD_CONFIG__AUTO_GAIN_LEVELS_validator(form, field):
    if field.data not in list(zip(*form.CCD_CONFIG__AUTO_GAIN_LEVELS_choices))[0]:
        raise ValidationError('Invalid number of levels')


def CCD_BIT_DEPTH_validator(form, field):
    if int(field.data) not in (0, 8, 10, 12, 14, 16):
        raise ValidationError('Bits must be 0, 8, 10, 12, 14, or 16 ')


def CCD_TEMP_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -50:
        raise ValidationError('Temperature must be greater than -50')


def FOCUS_DELAY_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Focus delay must be 1.0 or more')


def CFA_PATTERN_validator(form, field):
    if field.data not in list(zip(*form.CFA_PATTERN_choices))[0]:
        raise ValidationError('Please select a valid pattern')


def TEMP_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.TEMP_DISPLAY_choices))[0]:
        raise ValidationError('Please select the temperature system for display')


def IMAGE_ASI676MC_REPAIR__GAIN_validator(form, field):
    """Reject non-finite or destructive per-parity repair gains."""
    if not isinstance(field.data, (int, float)) or not math.isfinite(field.data):
        raise ValidationError('Enter a number, or restore the default shown below')

    if field.data < asi676mc.GAIN_MIN or field.data > asi676mc.GAIN_MAX:
        raise ValidationError(
            'Enter a gain between {0:g} and {1:g}, or restore the default'.format(
                asi676mc.GAIN_MIN,
                asi676mc.GAIN_MAX,
            )
        )


def TARGET_ADU_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Target ADU must be greater than 0')

    if field.data > 255 :
        raise ValidationError('Target ADU must be less than 255')


def TARGET_ADU_DAY_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Target ADU must be greater than 0')

    if field.data > 255 :
        raise ValidationError('Target ADU must be less than 255')


def TARGET_ADU_DEV_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Target ADU Deviation must be greater than 0')

    if field.data > 100 :
        raise ValidationError('Target ADU must be less than 100')


def TARGET_ADU_DEV_DAY_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Target ADU Deviation must be greater than 0')

    if field.data > 100 :
        raise ValidationError('Target ADU must be less than 100')


def ADU_ROI_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('ADU Region of Interest must be 0 or greater')


def SQM_ROI_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('SQM Region of Interest must be 0 or greater')


def IMAGE_LABEL_TEMPLATE_validator(form, field):
    now = datetime.now()
    now_utc = now.astimezone(timezone.utc)

    test_data = {
        'timestamp'  : now,
        'ts'         : now,
        'timestamp_utc' : now_utc,
        'ts_utc'     : now_utc,
        'day_date'   : now.date(),
        'exposure'   : 1.0,
        'rational_exp' : '',
        'gain'       : 1,  # originally int
        'gain_f'     : 1.0,
        'temp'       : -5.1,
        'temp_unit'  : 'C',
        'sqm'        : 8000.0,
        'stars'      : 1,
        'detections' : 'True',
        'owner'      : 'foobar',
        'sun_alt'    : 0.0,
        'sun_up'     : 'No',
        'sun_next_rise'     : '',
        'sun_next_rise_h'   : 0.0,
        'sun_next_set'      : '',
        'sun_next_set_h'    : 0.0,
        'sun_next_astro_twilight_rise'  : '',
        'sun_next_astro_twilight_rise_h': 0.0,
        'sun_next_astro_twilight_set'   : '',
        'sun_next_astro_twilight_set_h' : 0.0,
        'moon_alt'   : 0.0,
        'moon_phase' : 0.0,
        'moon_cycle' : 0.0,
        'moon_up'    : 'No',
        'sun_moon_sep'      : 0.0,
        'moon_next_rise'    : '',
        'moon_next_rise_h'  : 0.0,
        'moon_next_set'     : '',
        'moon_next_set_h'   : 0.0,
        'mercury_alt'  : 0.0,
        'mercury_up'   : 'No',
        'venus_alt'    : 0.0,
        'venus_phase'  : 0.0,
        'venus_up'     : 'No',
        'mars_alt'     : 0.0,
        'mars_up'      : 'No',
        'jupiter_alt'  : 0.0,
        'jupiter_up'   : 'No',
        'saturn_alt'   : 0.0,
        'saturn_up'    : 'No',
        'iss_alt'      : 0.0,
        'iss_up'       : 'No',
        'iss_next_h'   : 0.0,
        'iss_next_alt' : 0.0,
        'hst_alt'      : 0.0,
        'hst_up'       : 'No',
        'hst_next_h'   : 0.0,
        'hst_next_alt' : 0.0,
        'tiangong_alt'      : 0.0,
        'tiangong_up'       : 'No',
        'tiangong_next_h'   : 0.0,
        'tiangong_next_alt' : 0.0,
        'location'     : 'here',
        'kpindex'      : 0.0,
        'ovation_max'  : 0,
        'aurora_mag_bt' : 0.0,
        'aurora_mag_gsm_bz' : 0.0,
        'aurora_plasma_density' : 0.0,
        'aurora_plasma_speed' : 0.0,
        'aurora_plasma_temp' : 0,
        'aurora_n_hemi_gw' : 0,
        'aurora_s_hemi_gw' : 0,
        'smoke_rating' : 'foobar',
        'camera_sqm_raw_mag' : 0.0,
        'latitude'     : 0.0,
        'longitude'    : 0.0,
        'stack_method' : 'foo',
        'stack_count'  : 1,
        'sidereal_time' : 'foo',
        'stretch' : 'Off',
        'stretch_m1_gamma' : 0.0,
        'stretch_m1_stddevs' : 0.0,
        'dew_heater_status' : '',
        'fan_status' : '',
        'wind_dir' : '',
        'rain_status' : '',
        'custom_1' : '',
        'custom_2' : '',
        'custom_3' : '',
        'custom_4' : '',
        'custom_5' : '',
        'custom_6' : '',
        'custom_7' : '',
        'custom_8' : '',
        'custom_9' : '',
    }


    # system temperature sensors
    for x in range(60):
        test_data['sensor_temp_{0:d}'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_f'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_c'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_k'.format(x)] = 0.0


    # user sensors
    for x in range(60):
        test_data['sensor_user_{0:d}'.format(x)] = 0.0

    for x in range(100, 110):
        test_data['sensor_user_{0:d}'.format(x)] = 0.0


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def WEB_STATUS_TEMPLATE_validator(form, field):
    test_data = {
        'status' : '',
        'latitude' : 0.0,
        'longitude' : 0.0,
        'elevation' : 0,
        'sidereal_time' : '',
        'mode' : '',
        'mode_next_change'  : '',
        'mode_next_change_h': 0.0,
        'sun_alt' : 0.0,
        'sun_dir' : '',
        'sun_next_rise' : '',
        'sun_next_rise_h' : 0.0,
        'sun_next_set' : '',
        'sun_next_set_h' : 0.0,
        'sun_next_astro_twilight_rise'  : '',
        'sun_next_astro_twilight_rise_h': 0.0,
        'sun_next_astro_twilight_set'   : '',
        'sun_next_astro_twilight_set_h' : 0.0,
        'moon_alt' : 0.0,
        'moon_dir' : '',
        'moon_phase_str' : '',
        'moon_glyph' : '',
        'moon_phase' : 0.0,
        'moon_cycle_percent' : 0.0,
        'moon_next_rise' : '',
        'moon_next_rise_h' : 0.0,
        'moon_next_set' : '',
        'moon_next_set_h' : 0.0,
        'smoke_rating' : '',
        'smoke_rating_status' : '',
        'kpindex' : 0.0,
        'kpindex_rating' : '',
        'kpindex_trend' : '',
        'kpindex_status' : '',
        'ovation_max' : 0,
        'ovation_max_status' : '',
        'aurora_data_status' : '',
        'aurora_mag_bt' : 0.0,
        'aurora_mag_gsm_bz' : 0.0,
        'aurora_plasma_density' : 0.0,
        'aurora_plasma_speed' : 0.0,
        'aurora_plasma_temp' : 0,
        'aurora_n_hemi_gw' : 0,
        'aurora_s_hemi_gw' : 0,
        'camera_sqm_raw_mag' : 0.0,
        'owner' : '',
        'location' : '',
        'lens_name' : '',
        'alt' : 0.0,
        'az' : 0.0,
        'camera_name' : '',
        'camera_friendly_name' : '',

        'exposure'        : 0.0,
        'exp_elapsed'     : 0.0,
        'gain'            : 0.0,
        'binmode'         : 1,
        'temp'            : 0.0,
        'adu'             : 0.0,
        'sqm'             : 0.0,
        'stars'           : 0,
        'detections'      : 0,
        'process_elapsed' : 0.0,
        'uptime'          : 0,
        'uptime_str'      : '',
        'dew_heater_status' : '',
        'fan_status'        : '',
        'wind_dir'          : '',
        'rain_status'       : '',
    }


    # system temperature sensors
    for x in range(60):
        test_data['sensor_temp_{0:d}'.format(x)] = 0.0


    # user sensors
    for x in range(60):
        test_data['sensor_user_{0:d}'.format(x)] = 0.0

    for x in range(100, 110):
        test_data['sensor_user_{0:d}'.format(x)] = 0.0


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator(form, field):
    now = datetime.now()

    test_data = {
        'month'   : now.date(),
    }

    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def DETECT_MASK_validator(form, field):
    import numpy
    import cv2

    if not field.data:
        return

    folder_regex = r'^[a-zA-Z0-9_\.\-\/\ ]+$'
    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid file name')

    ext_regex = r'\.png$'
    if not re.search(ext_regex, field.data, re.IGNORECASE):
        raise ValidationError('Mask file must be a PNG')

    detect_mask_p = Path(field.data)

    try:
        if not detect_mask_p.exists():
            raise ValidationError('File does not exist')

        if not detect_mask_p.is_file():
            raise ValidationError('Not a file')

        with io.open(str(detect_mask_p), 'rb'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


    mask_data = cv2.imread(str(detect_mask_p), cv2.IMREAD_GRAYSCALE)
    if isinstance(mask_data, type(None)):
        raise ValidationError('File is not a valid image')

    if numpy.count_nonzero(mask_data == 255) == 0:
        raise ValidationError('Mask image is all black')


def MOON_OVERLAY__DARK_SIDE_SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Dark side scale must be 0.0 or more')

    if field.data > 0.9:
        raise ValidationError('Dark side scale must 0.9 or less')


def PYCURL_CAMERA__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\ \@\.\-\\]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def PYCURL_CAMERA__PASSWORD_validator(form, field):
    pass


def ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Sub-Exposure must be 1.0 or more')

    if field.data > 60.0:
        raise ValidationError('Sub-Exposure must be 60.0 or less')


def S3UPLOAD__URL_TEMPLATE_validator(form, field):
    urlt_regex = r'^[a-zA-Z0-9\.\-\:\/\{\}]+$'

    if not re.search(urlt_regex, field.data):
        raise ValidationError('Invalid URL template')


    if re.search(r'\/$', field.data):
        raise ValidationError('URL Template cannot end with a slash')


    test_data = {
        'host'      : 'foobar',
        'bucket'    : 'foobar',
        'region'    : 'foobar',
        'namespace' : 'foobar',
    }

    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def YOUTUBE__TITLE_TEMPLATE_validator(form, field):
    now = datetime.now()

    template_data = {
        'day_date'      : now.date(),
        'timeofday'     : 'Night',
        'asset_label'   : '',
    }

    try:
        field.data.format(**template_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def LIBCAMERA__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in list(zip(*form.LIBCAMERA__IMAGE_FILE_TYPE_choices))[0]:
        raise ValidationError('Please select a valid file type')


def LIBCAMERA__AWB_validator(form, field):
    if field.data not in list(zip(*form.LIBCAMERA__AWB_choices))[0]:
        raise ValidationError('Please select a valid AWB')


def LIBCAMERA__CAMERA_ID_validator(form, field):
    try:
        camera_id = int(field.data)
    except ValueError:
        raise ValidationError('Please enter a valid number')

    if camera_id < 0:
        raise ValidationError('Invalid camera id')

    if camera_id > 4:
        raise ValidationError('Invalid camera id')


def LIBCAMERA__EXTRA_OPTIONS_validator(form, field):
    if not field.data:
        return

    options_regex = r'^[a-zA-Z0-9_\.\,\-\:\/\ ]+$'
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


def PYCURL_CAMERA__URL_validator(form, field):
    if not field.data:
        return

    try:
        r = urlparse(field.data)
    except AttributeError:
        raise ValidationError('Invalid URL')

    if not r.scheme:
        raise ValidationError('Invalid URL')


def PYCURL_CAMERA__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in list(zip(*form.PYCURL_CAMERA__IMAGE_FILE_TYPE_choices))[0]:
        raise ValidationError('Please select a valid file type')


def TEST_CAMERA__WIDTH_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 100:
        raise ValidationError('Width must be 100 or greater')


def TEST_CAMERA__HEIGHT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 100:
        raise ValidationError('Height must be 100 or greater')


def TEST_CAMERA__BUBBLE_COUNT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 10:
        raise ValidationError('Count must be 10 or greater')


def FOCUSER__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.FOCUSER__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def TEMP_SENSOR__CLASSNAME_validator(form, field):
    sensors = list()
    for v in form.TEMP_SENSOR__CLASSNAME_choices.values():
        sensors.extend(list(zip(*v))[0])

    if field.data not in sensors:
        raise ValidationError('Invalid selection')


def TEMP_SENSOR__LABEL_validator(form, field):
    pass


def TEMP_SENSOR__TITLE_TEMPLATE_validator(form, field):
    test_data = {
        'name'  : '',
        'label' : '',
        'probe' : '',
    }


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY_validator(form, field):
    pass


def TEMP_SENSOR__ECOWITT_APPLICATIONKEY_validator(form, field):
    pass


def TEMP_SENSOR__MACADDRESS_validator(form, field):
    if not field.data:
        return

    macaddress_regex = r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$'

    if not re.match(macaddress_regex, field.data):
        raise ValidationError('Invalid MAC address')


def TEMP_SENSOR__SHT4X_MODE_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__SHT4X_MODE_choices))[0]:
        raise ValidationError('Invalid mode selection')


def TEMP_SENSOR__HDC302X_HEATER_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__HDC302X_HEATER_choices))[0]:
        raise ValidationError('Invalid heater selection')


def TEMP_SENSOR__SI7021_HEATER_LEVEL_validator(form, field):
    try:
        data_str = str(field.data)
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


    if data_str not in list(zip(*form.TEMP_SENSOR__SI7021_HEATER_LEVEL_choices))[0]:
        raise ValidationError('Invalid heater level')


def TEMP_SENSOR__TSL2561_GAIN_validator(form, field):
    try:
        data_i = int(field.data)
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))

    if data_i < 0:
        raise ValidationError('Invalid gain selection')

    if data_i > 1:
        raise ValidationError('Invalid gain selection')


def TEMP_SENSOR__TSL2561_INT_validator(form, field):
    try:
        data_i = int(field.data)
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))

    if data_i < 0:
        raise ValidationError('Invalid integration selection')

    if data_i > 2:
        raise ValidationError('Invalid integration selection')


def TEMP_SENSOR__TSL2591_GAIN_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__TSL2591_GAIN_choices))[0]:
        raise ValidationError('Invalid gain selection')


def TEMP_SENSOR__TSL2591_INT_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__TSL2591_INT_choices))[0]:
        raise ValidationError('Invalid integration selection')


def TEMP_SENSOR__VEML7700_GAIN_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__VEML7700_GAIN_choices))[0]:
        raise ValidationError('Invalid gain selection')


def TEMP_SENSOR__VEML7700_INT_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__VEML7700_INT_choices))[0]:
        raise ValidationError('Invalid integration selection')


def TEMP_SENSOR__SI1145_GAIN_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__SI1145_GAIN_choices))[0]:
        raise ValidationError('Invalid gain selection')


def TEMP_SENSOR__LTR390_GAIN_validator(form, field):
    if field.data not in list(zip(*form.TEMP_SENSOR__LTR390_GAIN_choices))[0]:
        raise ValidationError('Invalid gain selection')


def TEMP_SENSOR__AS3935_NOISE_LEVEL_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 1:
        raise ValidationError('Noise Level must be 1 to 7')

    if field.data > 7:
        raise ValidationError('Noise Level must be 1 to 7')


def TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 1:
        raise ValidationError('Spike Rejection must be 1 to 11')

    if field.data > 11:
        raise ValidationError('Spike Rejection must be 1 to 11')


def ADSB__IMAGE_LABEL_TEMPLATE_PREFIX_validator(form, field):
    pass


def ADSB__AIRCRAFT_LABEL_TEMPLATE_validator(form, field):
    test_data = {
        'id'        : '',
        'squawk'    : '',
        'flight'    : '',
        'hex'       : '',
        'latitude'  : 0.0,
        'longitude' : 0.0,
        'distance'  : 0.0,
        'distance_m'  : 0.0,
        'distance_ft' : 0.0,
        'distance_mi' : 0.0,
        'range'     : 0.0,
        'range_m'   : 0.0,
        'range_ft'  : 0.0,
        'range_mi'  : 0.0,
        'elevation' : 0.0,
        'elevation_m'  : 0.0,
        'elevation_ft' : 0.0,
        'elevation_mi' : 0.0,
        'altitude'  : 0.0,
        'altitude_m'  : 0.0,
        'altitude_ft' : 0.0,
        'altitude_mi' : 0.0,
        'alt'       : 0.0,
        'az'        : 0.0,
        'dir'       : '',
    }


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


def SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX_validator(form, field):
    pass


def SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator(form, field):
    test_data = {
        'title'     : '',
        'elevation' : 0.0,
        'alt'       : 0.0,
        'az'        : 0.0,
        'dir'       : '',
        'mag'       : 0.0,
        'sublat'    : 0.0,
        'latitude'  : 0.0,
        'sublong'   : 0.0,
        'longitude' : 0.0,
        'range'     : 0.0,
        'range_velocity' : 0.0,
    }


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


