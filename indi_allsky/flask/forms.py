import os
from pathlib import Path
import io
import re
import json
import time
from datetime import datetime
import tempfile
import psutil
import subprocess
import itertools

from passlib.hash import argon2

from .. import constants

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
from wtforms.widgets import PasswordInput
from wtforms.validators import DataRequired
from wtforms.validators import ValidationError

#from sqlalchemy import extract
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

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbMiniVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbPanoramaImageTable
from .models import IndiAllSkyDbPanoramaVideoTable
from .models import IndiAllSkyDbThumbnailTable

from . import db


def SQLALCHEMY_DATABASE_URI_validator(form, field):
    host_regex = r'^[a-zA-Z0-9_\.\-\:\/\@]+$'

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid URI')


def CAMERA_INTERFACE_validator(form, field):
    interfaces = list()
    for v in form.CAMERA_INTERFACE_choices.values():
        interfaces.extend(list(zip(*v))[0])

    if field.data not in interfaces:
        raise ValidationError('Invalid camera interface')


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


def INDI_CAMERA_NAME_validator(form, field):
    if not field.data:
        return

    camera_regex = r'^[a-zA-Z0-9\ \-]+$'

    if not re.search(camera_regex, field.data):
        raise ValidationError('Invalid camera name')


def OWNER_validator(form, field):
    if not field.data:
        return

    owner_regex = r'^[a-zA-Z0-9\_\.\ \-\@]+$'

    if not re.search(owner_regex, field.data):
        raise ValidationError('Invalid characters in owner name')


def LENS_NAME_validator(form, field):
    if not field.data:
        return

    lens_regex = r'^[a-zA-Z0-9\.\ \-\/]+$'

    if not re.search(lens_regex, field.data):
        raise ValidationError('Invalid lens name')


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


def ccd_GAIN_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Gain must be 0 or higher')


def ccd_BINNING_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Bin mode must be more than 0')

    if field.data > 4:
        raise ValidationError('Bin mode must be less than 4')


def CCD_EXPOSURE_MAX_validator(form, field):
    if field.data <= 0.0:
        raise ValidationError('Max Exposure must be more than 0')

    if field.data > 120.0:
        raise ValidationError('Max Exposure cannot be more than 120')


def CCD_EXPOSURE_DEF_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Default Exposure must be 0 or more')

    if field.data > 120.0:
        raise ValidationError('Default Exposure cannot be more than 120')


def CCD_EXPOSURE_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Minimum Exposure must be 0 or more')

    if field.data > 120.0:
        raise ValidationError('Minimum Exposure cannot be more than 120')


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


def TIMELAPSE_SKIP_FRAMES_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Skip frames must 0 or more')

    if field.data > 10:
        raise ValidationError('Skip frames must 10 or less')


def TIMELAPSE__PRE_PROCESSOR_validator(form, field):
    if field.data not in list(zip(*form.TIMELAPSE__PRE_PROCESSOR_choices))[0]:
        raise ValidationError('Invalid selection')


def TIMELAPSE__IMAGE_CIRCLE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 100:
        raise ValidationError('Diameter must be 100 or greater')


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
    if not field.data:
        return

    cfa_list = ('GRBG', 'RGGB', 'BGGR', 'GBRG')
    if field.data not in cfa_list:
        raise ValidationError('Please select a valid pattern')


def WB_FACTOR_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Balance factor must be 0 or greater')

    if field.data > 4.0:
        raise ValidationError('Balance factor must be less than 4.0')


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

    if field.data < 0.0:
        raise ValidationError('Gamma must be 0 or greater')

    if field.data > 3.0:
        raise ValidationError('Gamma must be less than 3.0')


def SCNR_ALGORITHM_validator(form, field):
    if not field.data:
        return

    scnr_list = ('average_neutral', 'maximum_neutral')
    if field.data not in scnr_list:
        raise ValidationError('Please select a valid algorithm')


def TEMP_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.TEMP_DISPLAY_choices))[0]:
        raise ValidationError('Please select the temperature system for display')


def PRESSURE_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.PRESSURE_DISPLAY_choices))[0]:
        raise ValidationError('Please select the pressure system for display')


def WINDSPEED_DISPLAY_validator(form, field):
    if field.data not in list(zip(*form.WINDSPEED_DISPLAY_choices))[0]:
        raise ValidationError('Please select the wind speed system for display')


def CCD_TEMP_SCRIPT_validator(form, field):
    if not field.data:
        return


    temp_script_p = Path(field.data)

    if not temp_script_p.exists():
        raise ValidationError('Temperature script does not exist')

    if not temp_script_p.is_file():
        raise ValidationError('Temperature script is not a file')

    if temp_script_p.stat().st_size == 0:
        raise ValidationError('Temperature script is empty')

    if not os.access(str(temp_script_p), os.X_OK):
        raise ValidationError('Temperature script is not executable')


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
        raise ValidationError('Temperature script returned exited abnormally')


    try:
        with io.open(str(tempjson_name_p), 'r') as tempjson_name_f:
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


def LOCATION_NAME_validator(form, field):
    if not field.data:
        return

    name_regex = r'^[a-zA-Z0-9_,\.\-\/\:\ ]+$'

    if not re.search(name_regex, field.data):
        raise ValidationError('Invalid name')


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


def CLAHE_CLIPLIMIT_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0:
        raise ValidationError('Clip limit must be greater than 0')

    if field.data > 60:
        raise ValidationError('Clip limit must be less than 60')


def CLAHE_GRIDSIZE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 4:
        raise ValidationError('Grid size must be 4 or greater')

    if field.data > 64:
        raise ValidationError('Clip limit must be 64 or less')


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


def IMAGE_LABEL_SYSTEM_validator(form, field):
    if not field.data:
        return

    if field.data not in ['opencv', 'pillow']:
        raise ValidationError('Unknown label system')


def IMAGE_LABEL_TEMPLATE_validator(form, field):
    now = datetime.now()

    test_data = {
        'timestamp'  : now,
        'ts'         : now,
        'day_date'   : now.date(),
        'exposure'   : 1.0,
        'rational_exp' : '',
        'gain'       : 1,
        'temp'       : -5.1,
        'temp_unit'  : 'C',
        'sqm'        : 8000.0,
        'stars'      : 1,
        'detections' : 'True',
        'owner'      : 'foobar',
        'sun_alt'    : 0.0,
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
    }


    for x in range(30):
        # temperature sensors
        test_data['sensor_temp_{0:d}'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_f'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_c'.format(x)] = 0.0
        test_data['sensor_temp_{0:d}_k'.format(x)] = 0.0

    for x in range(30):
        # other sensors
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
        'owner' : '',
        'location' : '',
        'lens_name' : '',
        'alt' : 0.0,
        'az' : 0.0,
        'camera_name' : '',
        'camera_friendly_name' : '',
    }


    try:
        field.data.format(**test_data)
    except KeyError as e:
        raise ValidationError('KeyError: {0:s}'.format(str(e)))
    except ValueError as e:
        raise ValidationError('ValueError: {0:s}'.format(str(e)))


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

        with io.open(str(web_extra_text_p), 'r'):
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
    if field.data not in ('jpg', 'png', 'tif', 'webp'):
        raise ValidationError('Please select a valid file type')


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


def IMAGE_FOLDER_validator(form, field):
    folder_regex = r'^[a-zA-Z0-9_\.\-\/]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid folder name')

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


def IMAGE_EXPORT_FOLDER_validator(form, field):
    folder_regex = r'^[a-zA-Z0-9_\.\-\/]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid folder name')

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


def IMAGE_EXPORT_RAW_validator(form, field):
    if not field.data:
        return

    if field.data not in ('png', 'tif', 'jpg', 'jp2', 'webp'):
        raise ValidationError('Please select a valid file type')


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

        with io.open(str(image_extra_text_p), 'r'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


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

        with io.open(str(detect_mask_p), 'r'):
            pass
    except PermissionError as e:
        raise ValidationError(str(e))


    mask_data = cv2.imread(str(detect_mask_p), cv2.IMREAD_GRAYSCALE)
    if isinstance(mask_data, type(None)):
        raise ValidationError('File is not a valid image')

    if numpy.count_nonzero(mask_data == 255) == 0:
        raise ValidationError('Mask image is all black')


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

        with io.open(str(overlay_p), 'r'):
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


def IMAGE_SCALE_validator(form, field):
    if field.data < 1:
        raise ValidationError('Image Scaling must be 1 or greater')

    if field.data > 100:
        raise ValidationError('Image Scaling must be 100 or less')


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


def FISH2PANO__ROTATE_ANGLE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < -180:
        raise ValidationError('Rotation angle must be -180 or greater')

    if field.data > 180:
        raise ValidationError('Rotation angle must be 180 or less')


def FISH2PANO__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.1:
        raise ValidationError('Scale must be 0.1 or greater')

    if field.data > 1.0:
        raise ValidationError('Scale must be 1.0 or less')


def FISH2PANO__MODULUS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Modulus must be 1 or greater')


def IMAGE_CROP_ROI_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Crop Region of Interest must be 0 or greater')


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

    # not validating max


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


def TIMELAPSE_EXPIRE_DAYS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 1:
        raise ValidationError('Timelapse Expiration must be 1 or greater')


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


def FFMPEG_VFSCALE_validator(form, field):
    if not field.data:
        return

    scale_regex = r'^[a-z0-9\-\*\.]+\:[a-z0-9\-\*\.]+$'
    if not re.search(scale_regex, field.data):
        raise ValidationError('Invalid scale option')


def FFMPEG_CODEC_validator(form, field):
    if field.data not in list(zip(*form.FFMPEG_CODEC_choices))[0]:
        raise ValidationError('Invalid codec option')


def FFMPEG_EXTRA_OPTIONS_validator(form, field):
    if not field.data:
        return

    options_regex = r'^[a-zA-Z0-9_\.\,\-\:\;\/\ \=\'\*\[\]\(\)]+$'
    if not re.search(options_regex, field.data):
        raise ValidationError('Invalid characters')


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


def MOON_OVERLAY__X_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def MOON_OVERLAY__Y_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


def MOON_OVERLAY__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.1:
        raise ValidationError('Image scale must be 0.1 or more')

    if field.data > 2.0:
        raise ValidationError('Image scale must be 2.0 or less')


def MOON_OVERLAY__DARK_SIDE_SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Dark side scale must be 0.0 or more')

    if field.data > 0.9:
        raise ValidationError('Dark side scale must 0.9 or less')


def LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 10:
        raise ValidationError('Height must be 10 or more')

    if field.data > 100:
        raise ValidationError('Height must 100 or less')


def LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Border must be 0 or more')

    if field.data > 10:
        raise ValidationError('Border must 10 or less')


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


def LIGHTGRAPH_OVERLAY__SCALE_validator(form, field):
    if not isinstance(field.data, (int, float)):
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


def IMAGE_BORDER_SIDE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Border must be 0 or greater')

    if field.data > 1000:
        raise ValidationError('Border must be less than 1000')


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


def FILETRANSFER__HOST_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9_\.\-]+$'  # include _ for docker

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def MQTTPUBLISH__TRANSPORT_validator(form, field):
    valid_transports = (
        'tcp',
        'websockets',
    )

    if field.data not in valid_transports:
        raise ValidationError('Invalid transport')


def MQTTPUBLISH__HOST_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9_\.\-]+$'  # include _ for docker

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


def FILETRANSFER__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\@\.\-\\]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


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


def PYCURL_CAMERA__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def ADSB__USERNAME_validator(form, field):
    if not field.data:
        return

    username_regex = r'^[a-zA-Z0-9_\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def ADSB__DUMP1090_URL_validator(form, field):
    if not field.data:
        return


def FILETRANSFER__PASSWORD_validator(form, field):
    pass


def MQTTPUBLISH__PASSWORD_validator(form, field):
    pass


def SYNCAPI__APIKEY_validator(form, field):
    pass


def PYCURL_CAMERA__PASSWORD_validator(form, field):
    pass


def ADSB__PASSWORD_validator(form, field):
    pass


def ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Sub-Exposure must be 1.0 or more')

    if field.data > 60.0:
        raise ValidationError('Sub-Exposure must be 60.0 or less')


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


def SYNCAPI__TIMEOUT_validator(form, field):
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

        with io.open(str(file_name_p), 'r'):
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

        with io.open(str(file_name_p), 'r'):
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
    folder_regex = r'^[a-zA-Z0-9_\.\-\/\{\}\:\%\~]+$'

    if not re.search(folder_regex, field.data):
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


def FILETRANSFER__UPLOAD_IMAGE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Image Upload must be 0 or greater')


def SYNCAPI__UPLOAD_IMAGE_validator(form, field):
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


def S3UPLOAD__URL_TEMPLATE_validator(form, field):
    urlt_regex = r'^[a-zA-Z0-9\.\-\:\/\{\}]+$'

    if not re.search(urlt_regex, field.data):
        raise ValidationError('Invalid URL template')


    slash_regex = r'\/$'

    if re.search(slash_regex, field.data):
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


def MQTTPUBLISH__BASE_TOPIC_validator(form, field):
    topic_regex = r'^[a-zA-Z0-9_\-\/]+$'

    if not re.search(topic_regex, field.data):
        raise ValidationError('Invalid characters in base topic')

    if re.search(r'^\/', field.data):
        raise ValidationError('Base topic cannot begin with slash')

    if re.search(r'\/$', field.data):
        raise ValidationError('Base topic cannot end with slash')


def MQTTPUBLISH__QOS_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data not in (0, 1, 2):
        raise ValidationError('Invalid QoS')


def SYNCAPI__BASEURL_validator(form, field):
    url_regex = r'^[a-zA-Z0-9\-\/\.\:\\]+$'

    if not re.search(url_regex, field.data):
        raise ValidationError('Invalid characters in URL')

    if not re.search(r'^https?\:\/\/', field.data):
        raise ValidationError('URL should begin with https://')

    if re.search(r'\/$', field.data):
        raise ValidationError('URL cannot end with slash')

    if re.search(r'localhost', field.data):
        raise ValidationError('Do not sync to localhost, bad things happen')

    if re.search(r'127\.0\.0\.1', field.data):
        raise ValidationError('Do not sync to localhost, bad things happen')

    if re.search(r'\:\:1', field.data):
        raise ValidationError('Do not sync to localhost, bad things happen')


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


def YOUTUBE__CATEGORY_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid category number')


def YOUTUBE__TAGS_STR_validator(form, field):
    if not field.data:
        return


def FITSHEADER_KEY_validator(form, field):
    header_regex = r'^[a-zA-Z0-9\-]+$'

    if not re.search(header_regex, field.data):
        raise ValidationError('Invalid characters in header')

    if len(field.data) > 8:
        raise ValidationError('Header must be 8 characters or less')


def LIBCAMERA__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in ('dng', 'jpg', 'png'):
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


def PYCURL_CAMERA__URL_validator(form, field):
    if not field.data:
        return


def PYCURL_CAMERA__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in ('jpg', 'png'):
        raise ValidationError('Please select a valid file type')


def FOCUSER__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.FOCUSER__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


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
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')

    if field.data < 0:
        raise ValidationError('Threshold delta must be 0 or greater')


def DEW_HEATER__MANUAL_TARGET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


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
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


def FAN__TARGET_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter a valid number')


def GENERIC_GPIO__CLASSNAME_validator(form, field):
    if field.data not in list(zip(*form.GENERIC_GPIO__CLASSNAME_choices))[0]:
        raise ValidationError('Invalid selection')


def TEMP_SENSOR__CLASSNAME_validator(form, field):
    sensors = list()
    for v in form.TEMP_SENSOR__CLASSNAME_choices.values():
        sensors.extend(list(zip(*v))[0])

    if field.data not in sensors:
        raise ValidationError('Invalid selection')


def TEMP_SENSOR__LABEL_validator(form, field):
    pass


def TEMP_SENSOR__I2C_ADDRESS_validator(form, field):
    try:
        int(field.data, 16)
    except ValueError as e:
        raise ValidationError('Invalid HEX address: {0:s}'.format(str(e)))


def TEMP_SENSOR__OPENWEATHERMAP_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__WUNDERGROUND_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__ASTROSPHERIC_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__AMBIENTWEATHER_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY_validator(form, field):
    pass


def TEMP_SENSOR__ECOWITT_APIKEY_validator(form, field):
    pass


def TEMP_SENSOR__ECOWITT_APPLICATIONKEY_validator(form, field):
    pass


def TEMP_SENSOR__MACADDRESS_validator(form, field):
    if not field.data:
        return

    macaddress_regex = r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$'

    if not re.match(macaddress_regex, field.data):
        raise ValidationError('Invalid MAC address')


def SENSOR_SLOT_validator(form, field):
    slots = list()
    for v in form.SENSOR_SLOT_choices.values():
        slots.extend(list(zip(*v))[0])

    if field.data not in slots:
        raise ValidationError('Invalid selection')


def SENSOR_USER_VAR_SLOT_validator(form, field):
    if field.data not in list(zip(*form.SENSOR_USER_VAR_SLOT_choices))[0]:
        raise ValidationError('Invalid selection')


def DEVICE_PIN_NAME_validator(form, field):
    if not field.data:
        return


    class_regex = r'^[a-zA-Z0-9_,\-\/]+$'

    if not re.search(class_regex, field.data):
        raise ValidationError('Invalid PIN name')


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
        'range'     : 0.0,
        'elevation' : 0.0,
        'altitude'  : 0.0,
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


def ADSB__LABEL_LIMIT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 1:
        raise ValidationError('Limit must be greater than 0')

    if field.data > 20:
        raise ValidationError('Limit must be 20 or less')


def SATELLITE_TRACK__ALT_DEG_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Minimum altitude must be 0 or more')

    if field.data > 90:
        raise ValidationError('Minimum altitude must be less than 90')


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


def SATELLITE_TRACK__LABEL_LIMIT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter a valid number')


    if field.data < 1:
        raise ValidationError('Limit must be greater than 0')

    if field.data > 20:
        raise ValidationError('Limit must be 20 or less')


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


class IndiAllskyConfigForm(FlaskForm):
    CAMERA_INTERFACE_choices = {
        'INDI' : (
            ('indi', 'INDI'),
        ),
        'libcamera' : (
            ('libcamera_imx477', 'libcamera IMX477'),
            ('libcamera_imx378', 'libcamera IMX378'),
            ('libcamera_imx708', 'libcamera IMX708'),
            ('libcamera_imx519', 'libcamera IMX519'),
            ('libcamera_imx462', 'libcamera IMX462'),
            ('libcamera_imx327', 'libcamera IMX327'),
            ('libcamera_imx678', 'libcamera IMX678 Darksee'),
            ('libcamera_imx500_ai', 'libcamera IMX500 AI'),
            ('libcamera_imx283', 'libcamera IMX283 Klarity/OneInchEye'),
            ('libcamera_imx296_gs', 'libcamera IMX296 GS'),
            ('libcamera_imx290', 'libcamera IMX290'),
            ('libcamera_imx298', 'libcamera IMX298'),
            ('libcamera_imx219', 'libcamera IMX219'),
            ('libcamera_ov5647', 'libcamera OV5647'),
            ('libcamera_64mp_hawkeye', 'libcamera 64mp HawkEye'),
            ('libcamera_64mp_owlsight', 'libcamera 64mp OwlSight'),
        ),
        'Network Web Cameras' : (
            ('pycurl_camera', 'pyCurl Camera'),
        ),
        'Special Function' : (
            ('indi_accumulator', 'INDI Accumulator'),
            ('indi_passive', 'INDI (Passive)'),
        ),
    }

    CCD_BIT_DEPTH_choices = (
        ('0', 'Auto Detect'),
        ('8', '8'),
        ('10', '10'),
        ('12', '12'),
        ('14', '14'),
        ('16', '16'),
    )

    TEMP_DISPLAY_choices = (
        ('c', 'Celsius'),
        ('f', 'Fahrenheit'),
        ('k', 'Kelvin'),
    )

    PRESSURE_DISPLAY_choices = (
        ('hPa', 'hectoPascals (hPa)'),
        ('psi', 'PSI'),
        ('inHg', 'Inches of Mercury (inHg)'),
        ('mmHg', 'Millimeters of Mercury (mmHg)'),
    )

    WINDSPEED_DISPLAY_choices = (
        ('ms', 'Meters/second (m/s)'),
        ('knots', 'Knots'),
        ('mph', 'Miles/hour (mph)'),
        ('kph', 'Kilometers/hour (km/h)'),
    )

    IMAGE_FILE_TYPE_choices = (
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
        #('webp', 'WebP'),  # ffmpeg support broken
        ('tif', 'TIFF'),
    )

    CFA_PATTERN_choices = (
        ('', 'Auto Detect'),
        ('RGGB', 'RGGB'),
        ('GRBG', 'GRBG'),
        ('BGGR', 'BGGR'),
        ('GBRG', 'GBRG'),
    )

    SCNR_ALGORITHM_choices = (
        ('', 'Disabled'),
        ('average_neutral', 'Average Neutral'),
        ('maximum_neutral', 'Maximum Neutral'),
    )

    IMAGE_EXPORT_RAW_choices = (
        ('', 'Disabled'),
        ('png', 'PNG'),
        ('tif', 'TIFF'),
        ('jp2', 'JPEG 2000'),
        ('webp', 'WEBP'),
        ('jpg', 'JPEG'),
    )

    ADU_FOV_DIV_choices = (
        ('2', '100%'),
        ('3', '66%'),
        ('4', '50%'),
        ('6', '33%'),
    )

    SQM_FOV_DIV_choices = (
        ('2', '100%'),
        ('3', '66%'),
        ('4', '50%'),
        ('6', '33%'),
    )

    IMAGE_STACK_METHOD_choices = (
        ('maximum', 'Maximum'),
        ('average', 'Average'),
        ('minimum', 'Minimum'),
    )

    IMAGE_STACK_COUNT_choices = (
        ('1', 'Disabled'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
    )

    IMAGE_ROTATE_choices = (
        ('', 'Disabled'),
        ('ROTATE_90_CLOCKWISE', '90° Clockwise'),
        ('ROTATE_90_COUNTERCLOCKWISE', '90° Counterclockwise'),
        ('ROTATE_180', '180°'),
    )

    FFMPEG_VFSCALE_choices = {
        'Standard' : (
            ('', 'No Scaling'),
            ('-2:2160', 'Height 2160px - [-2:2160] - 2GB RAM'),
            ('-2:1440', 'Height 1440px - [-2:1440] - 2GB RAM'),
            ('-2:1080', 'Height 1080px - [-2:1080] - 1GB RAM'),
            ('-2:720', 'Height 720px - [-2:720] - 1GB RAM'),
            ('-2:480', 'Height 480px - [-2:480] - <1GB RAM'),
        ),
        'Legacy' : (
            ('-1:2304', 'Height 2304px - [-1:2304] - 75% (imx477-only)'),
            ('-1:1520', 'Height 1520px - [-1:1520] - 50% (imx477-only)'),
            ('-1:760', 'Height 760px - [-1:760] - 25% (imx477-only)'),
        ),
        'Do Not Use' : (
            ('iw*.75:ih*.75', '75% - [iw*.75:ih*.75] - Do not use'),
            ('iw*.5:ih*.5', '50% - [iw*.5:ih*.5] - Do not use'),
            ('iw*.25:ih*.25', '25% - [iw*.25:ih*.25] - Do not use'),
            ('iw*.75:-2', '75% - [iw*.75:-2] - Do not use'),
            ('iw*.5:-2', '50% - [iw*.5:-2] - Do not use'),
            ('iw*.25:-2', '25% - [iw*.25:-2] - Do not use'),
        ),
    }

    FFMPEG_CODEC_choices = (
        ('libx264', 'x264'),
        ('libvpx', 'webm'),
        ('h264_v4l2m2m', 'h264 (v4l2m2m) - Raspberry Pi'),
        ('h264_qsv', 'h264 (QSV) - Intel Quick Sync Video'),
        ('h264_omx', 'h264 (OMX) - Raspberry Pi (32-bit only)'),
        ('libx265', 'x265 hevc - DO NOT USE'),
        ('hevc_v4l2m2m', 'h265 hevc (v4l2m2m) - DO NOT USE'),
    )


    TIMELAPSE__PRE_PROCESSOR_choices = (
        ('standard', 'Standard - No Processing'),
        ('wrap_keogram', 'Wrap Keogram Around Image Circle'),
    )


    ORB_PROPERTIES__MODE_choices = (
        ('ha', 'Local Hour Angle'),
        ('az', 'Azimuth'),
        ('alt', 'Altitude'),
        ('off', 'Off'),
    )

    IMAGE_LABEL_SYSTEM_choices = (
        ('', 'Off'),
        ('pillow', 'Pillow'),
        ('opencv', 'OpenCV'),
    )

    TEXT_PROPERTIES__FONT_FACE_choices = (
        ('FONT_HERSHEY_SIMPLEX', 'Sans-Serif'),
        ('FONT_HERSHEY_PLAIN', 'Sans-Serif (small)'),
        ('FONT_HERSHEY_DUPLEX', 'Sans-Serif (complex)'),
        ('FONT_HERSHEY_COMPLEX', 'Serif'),
        ('FONT_HERSHEY_TRIPLEX', 'Serif (complex)'),
        ('FONT_HERSHEY_COMPLEX_SMALL', 'Serif (small)'),
        ('FONT_HERSHEY_SCRIPT_SIMPLEX', 'Script'),
        ('FONT_HERSHEY_SCRIPT_COMPLEX', 'Script (complex)'),
    )

    TEXT_PROPERTIES__PIL_FONT_FILE_choices = (
        ('fonts-freefont-ttf/FreeSans.ttf', 'Free Sans'),
        ('fonts-freefont-ttf/FreeSansBold.ttf', 'Free Sans Bold'),
        ('fonts-freefont-ttf/FreeSansOblique.ttf', 'Free Oblique'),
        ('fonts-freefont-ttf/FreeSansBoldOblique.ttf', 'Free Bold Oblique'),
        ('fonts-freefont-ttf/FreeSerif.ttf', 'Free Serif'),
        ('fonts-freefont-ttf/FreeSerifBold.ttf', 'Free Serif Bold'),
        ('fonts-freefont-ttf/FreeSerifItalic.ttf', 'Free Serif Italic'),
        ('fonts-freefont-ttf/FreeSerifBoldItalic.ttf', 'Free Serif Bold Italic'),
        ('fonts-freefont-ttf/FreeMono.ttf', 'Free Mono'),
        ('fonts-freefont-ttf/FreeMonoBold.ttf', 'Free Mono Bold'),
        ('fonts-freefont-ttf/FreeMonoOblique.ttf', 'Free Mono Oblique'),
        ('fonts-freefont-ttf/FreeMonoBoldOblique.ttf', 'Free Mono Bold Oblique'),
        ('liberation2/LiberationMono-Regular.ttf', 'Liberation Mono'),
        ('liberation2/LiberationMono-Italic.ttf', 'Liberation Mono Italic'),
        ('liberation2/LiberationMono-Bold.ttf', 'Liberation Mono Bold'),
        ('liberation2/LiberationMono-BoldItalic.ttf', 'Liberation Mono Bold Italic'),
        ('liberation2/LiberationSans-Regular.ttf', 'Liberation Sans'),
        ('liberation2/LiberationSans-Italic.ttf', 'Liberation Sans Italic'),
        ('liberation2/LiberationSans-Bold.ttf', 'Liberation Sans Bold'),
        ('liberation2/LiberationSans-BoldItalic.ttf', 'Liberation Sans Bold Italic'),
        ('liberation2/LiberationSerif-Regular.ttf', 'Liberation Serif'),
        ('liberation2/LiberationSerif-Italic.ttf', 'Liberation Serif Italic'),
        ('liberation2/LiberationSerif-Bold.ttf', 'Liberation Serif Bold'),
        ('liberation2/LiberationSerif-BoldItalic.ttf', 'Liberation Serif Bold Italic'),
        ('hack/Hack-Regular.ttf', 'Hack Sans Mono'),
        ('hack/Hack-Italic.ttf', 'Hack Sans Mono Italic'),
        ('hack/Hack-Bold.ttf', 'Hack Sans Mono Bold'),
        ('hack/Hack-BoldItalic.ttf', 'Hack Sans Mono Bold Italic'),
        ('intel-one-mono/intelone-mono-font-family-regular.ttf', 'Intel One Mono Regular'),
        ('intel-one-mono/intelone-mono-font-family-italic.ttf', 'Intel One Mono Italic'),
        ('intel-one-mono/intelone-mono-font-family-light.ttf', 'Intel One Mono Light'),
        ('intel-one-mono/intelone-mono-font-family-lightitalic.ttf', 'Intel One Mono Light Italic'),
        ('intel-one-mono/intelone-mono-font-family-medium.ttf', 'Intel One Mono Medium'),
        ('intel-one-mono/intelone-mono-font-family-mediumitalic.ttf', 'Intel One Mono Medium Italic'),
        ('intel-one-mono/intelone-mono-font-family-bold.ttf', 'Intel One Mono Bold '),
        ('intel-one-mono/intelone-mono-font-family-bolditalic.ttf', 'Intel One Mono Bold Italic'),
        ('custom', 'Custom (below)'),
    )

    FILETRANSFER__CLASSNAME_choices = (
        ('pycurl_sftp', 'PycURL SFTP [22]'),
        ('pycurl_ftpes', 'PycURL FTPS [21] (FTPES)'),
        ('pycurl_ftp', 'PycURL FTP [21] *no encryption*'),
        ('pycurl_webdav_https', 'PycURL WebDAV HTTPS [443]'),
        ('paramiko_sftp', 'Paramiko SFTP [22]'),
        ('python_ftp', 'Python FTP [21] *no encryption*'),
        ('python_ftpes', 'Python FTPS [21] (FTPES)'),
        ('pycurl_ftps', 'PycURL FTPS [990] (Uncommon)'),
    )

    S3UPLOAD__CLASSNAME_choices = (
        ('boto3_s3', 'AWS S3 (boto3)'),
        ('boto3_minio', 'Minio (boto3)'),
        ('libcloud_s3', 'Apache Libcloud (AWS)'),
        ('gcp_storage', 'Google Cloud Storage'),
        ('oci_storage', 'Oracle OCI Storage'),
    )

    MQTTPUBLISH__TRANSPORT_choices = (
        ('tcp', 'tcp'),
        ('websockets', 'websockets'),
    )

    LIBCAMERA__IMAGE_FILE_TYPE_choices = (
        ('jpg', 'JPEG'),
        ('dng', 'DNG (raw)'),
        ('png', 'PNG'),
    )

    LIBCAMERA__AWB_choices = (
        ('auto', 'Auto'),
        ('incandescent', 'Incandescent'),
        ('tungsten', 'Tungsten'),
        ('fluorescent', 'Fluorescent'),
        ('indoor', 'Indoor'),
        ('daylight', 'Daylight'),
        ('cloudy', 'Cloudy'),
        ('custom', 'Custom'),
    )

    LIBCAMERA__CAMERA_ID_choices = (
        ('0', '0'),
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
    )

    PYCURL_CAMERA__IMAGE_FILE_TYPE_choices = (
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
    )

    YOUTUBE__PRIVACY_STATUS_choices = (
        ('private', 'Private'),
        ('public', 'Public'),
        ('unlisted', 'Unlisted'),
    )


    IMAGE_STRETCH__CLASSNAME_choices = (
        ('', 'None'),
        ('mode1_stddev_cutoff', 'Standard Deviation Cutoff (Original)'),
        ('mode2_mtf', 'Midtone Transfer Function Transformation'),
        ('mode2_mtf_x2', 'Midtone Transfer Function Transformation (Double)'),
    )


    FOCUSER__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_focuser_28byj_64', '28BYJ-48 Stepper (1/64) ULN2003 - GPIO (4 pins)'),
        ('blinka_focuser_28byj_16', '28BYJ-48 Stepper (1/16) ULN2003 - GPIO (4 pins)'),
        ('blinka_focuser_a4988_nema17_full', 'A4988 NEMA17 Stepper - Full Step - GPIO (2 pins)'),
        ('blinka_focuser_a4988_nema17_half', 'A4988 NEMA17 Stepper - Half Step - GPIO (3 pins)'),
        ('serial_focuser_28byj_64', '28BYJ-48 Stepper (1/64) ULN2003 - Serial Port'),
        ('focuser_simulator', 'Focuser Simulator'),
    )

    DEW_HEATER__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_dew_heater_standard', 'Dew Heater - Standard'),
        ('blinka_dew_heater_pwm', 'Dew Heater - PWM'),
        ('serial_dew_heater_pwm', 'Dew Heater - PWM (Serial Port)'),
    )

    FAN__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_fan_standard', 'Fan - Standard'),
        ('blinka_fan_pwm', 'Fan - PWM'),
        ('serial_fan_pwm', 'Fan - PWM (Serial Port)'),
    )

    GENERIC_GPIO__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_gpio_standard', 'GPIO - Standard'),
    )

    TEMP_SENSOR__CLASSNAME_choices = {
        'Disabled' : (
            ('', 'None'),
        ),
        'API Services' : (
            ('temp_api_openweathermap', 'OpenWeather API (10)'),
            ('temp_api_weatherunderground', 'Weather Underground API (9)'),
            ('temp_api_astrospheric', 'Astrospheric API (6)'),
            ('temp_api_ambientweather', 'AmbientWeather API (10)'),
            ('temp_api_ecowitt', 'Ecowitt API (10)'),
        ),
        'Temperature Sensors' : (
            ('kernel_temp_sensor_ds18x20_w1', 'DS18x20 - Temp (1)'),
            ('blinka_temp_sensor_dht22', 'DHT22/AM2302 - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_dht21', 'DHT21/AM2301 - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_dht11', 'DHT11 - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_bmp180_i2c', 'BMP180 i2c - Temp/Pres (2)'),
            ('blinka_temp_sensor_bme280_i2c', 'BMP/BME280 i2c - Temp/RH/Pres/DP (4)'),
            ('blinka_temp_sensor_bme280_spi', 'BMP/BME280 SPI - Temp/RH/Pres/DP (4)'),
            ('blinka_temp_sensor_bme680_i2c', 'BME680 i2c - Temp/RH/Pres/Gas/DP (5)'),
            ('blinka_temp_sensor_bme680_spi', 'BME680 SPI - Temp/RH/Pres/Gas/DP (5)'),
            ('blinka_temp_sensor_bmp3xx_i2c', 'BMP3xx i2c - Temp/Pres (2)'),
            ('blinka_temp_sensor_bmp3xx_spi', 'BMP3xx SPI - Temp/Pres (2)'),
            ('blinka_temp_sensor_si7021_i2c', 'Si7021 i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_sht3x_i2c', 'SHT3x i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_sht4x_i2c', 'SHT40/41/45 i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_htu21d_i2c', 'HTU21D i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_htu31d_i2c', 'HTU31D i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_ahtx0_i2c', 'AHT10/20 i2c - Temp/RH/DP (3)'),
            ('blinka_temp_sensor_scd30_i2c', 'SCD-30 i2c - Temp/RH/CO2/DP (4)'),
            ('blinka_temp_sensor_scd4x_i2c', 'SCD-4x i2c - Temp/RH/CO2/DP (4)'),
            ('blinka_temp_sensor_hdc302x_i2c', 'HDC302x i2c - Temp/RH/DP (3)'),
            ('cpads_temp_sensor_tmp36_ads1015_i2c', 'TMP36 ADS1015 i2c - Temp (1)'),
            ('cpads_temp_sensor_tmp36_ads1115_i2c', 'TMP36 ADS1115 i2c - Temp (1)'),
            ('cpads_temp_sensor_lm35_ads1015_i2c', 'LM35 ADS1015 i2c - Temp (1)'),
            ('cpads_temp_sensor_lm35_ads1115_i2c', 'LM35 ADS1115 i2c - Temp (1)'),
            ('blinka_temp_sensor_mlx90614_i2c', 'MLX90614 i2c - Temp/SkyTemp (2)'),
            ('blinka_temp_sensor_mlx90640_i2c', 'MLX90640 i2c - SkyTemp (1)'),
        ),
        'Light/Lux Sensors' : (
            ('blinka_light_sensor_tsl2561_i2c', 'TSL2561 i2c - Lux/Full/IR (3)'),
            ('blinka_light_sensor_tsl2591_i2c', 'TSL2591 i2c - Lux/Vis/IR/Full (4)'),
            ('blinka_light_sensor_veml7700_i2c', 'VEML7700 i2c - Lux/Light/White (3)'),
            ('blinka_light_sensor_bh1750_i2c', 'BH1750 i2c - Lux (1)'),
            ('blinka_light_sensor_si1145_i2c', 'SI1145 i2c - Vis/IR/UV (3)'),
            ('blinka_light_sensor_ltr390_i2c', 'LTR390 i2c - UV/Vis/UVI/Lux (4)'),
        ),
        'Remote' : (
            ('mqtt_broker_sensor', 'MQTT Broker Sensor - (5)'),
        ),
        'Testing' : (
            ('sensor_data_generator', 'Test Data Generator - (7)'),
        ),
    }

    SENSOR_USER_VAR_SLOT_choices = (
        ('sensor_user_10', 'User Slot 10'),
        ('sensor_user_11', 'User Slot 11'),
        ('sensor_user_12', 'User Slot 12'),
        ('sensor_user_13', 'User Slot 13'),
        ('sensor_user_14', 'User Slot 14'),
        ('sensor_user_15', 'User Slot 15'),
        ('sensor_user_16', 'User Slot 16'),
        ('sensor_user_17', 'User Slot 17'),
        ('sensor_user_18', 'User Slot 18'),
        ('sensor_user_19', 'User Slot 19'),
        ('sensor_user_20', 'User Slot 20'),
        ('sensor_user_21', 'User Slot 21'),
        ('sensor_user_22', 'User Slot 22'),
        ('sensor_user_23', 'User Slot 23'),
        ('sensor_user_24', 'User Slot 24'),
        ('sensor_user_25', 'User Slot 25'),
        ('sensor_user_26', 'User Slot 26'),
        ('sensor_user_27', 'User Slot 27'),
        ('sensor_user_28', 'User Slot 28'),
        ('sensor_user_29', 'User Slot 29'),
    )

    SENSOR_SLOT_choices = {
        'User Sensors' : (
            ['sensor_user_0', '(0) User Slot - Camera Temp'],  # mutable
            ['sensor_user_1', '(1) User Slot - Dew Heater Level'],
            ['sensor_user_2', '(2) User Slot - Dew Point'],
            ['sensor_user_3', '(3) User Slot - Frost Point'],
            ['sensor_user_4', '(4) User Slot - Fan Level'],
            ['sensor_user_5', '(5) User Slot - Heat Index'],
            ['sensor_user_6', '(6) User Slot - Wind Dir (Degrees)'],
            ['sensor_user_7', '(7) User Slot - SQM'],
            ['sensor_user_8', 'User Slot - Future'],
            ['sensor_user_9', 'User Slot - Future'],
            ['sensor_user_10', 'User Slot 10'],
            ['sensor_user_11', 'User Slot 11'],
            ['sensor_user_12', 'User Slot 12'],
            ['sensor_user_13', 'User Slot 13'],
            ['sensor_user_14', 'User Slot 14'],
            ['sensor_user_15', 'User Slot 15'],
            ['sensor_user_16', 'User Slot 16'],
            ['sensor_user_17', 'User Slot 17'],
            ['sensor_user_18', 'User Slot 18'],
            ['sensor_user_19', 'User Slot 19'],
            ['sensor_user_20', 'User Slot 20'],
            ['sensor_user_21', 'User Slot 21'],
            ['sensor_user_22', 'User Slot 22'],
            ['sensor_user_23', 'User Slot 23'],
            ['sensor_user_24', 'User Slot 24'],
            ['sensor_user_25', 'User Slot 25'],
            ['sensor_user_26', 'User Slot 26'],
            ['sensor_user_27', 'User Slot 27'],
            ['sensor_user_28', 'User Slot 28'],
            ['sensor_user_29', 'User Slot 29'],
        ),
        'System Sensors' : (
            ['sensor_temp_0', '(0) System Temp - Camera Temp'],
            ['sensor_temp_1', 'System Temp - Future'],
            ['sensor_temp_2', 'System Temp - Future'],
            ['sensor_temp_3', 'System Temp - Future'],
            ['sensor_temp_4', 'System Temp - Future'],
            ['sensor_temp_5', 'System Temp - Future'],
            ['sensor_temp_6', 'System Temp - Future'],
            ['sensor_temp_7', 'System Temp - Future'],
            ['sensor_temp_8', 'System Temp - Future'],
            ['sensor_temp_9', 'System Temp - Future'],
            ['sensor_temp_10', 'System Temp 10'],
            ['sensor_temp_11', 'System Temp 11'],
            ['sensor_temp_12', 'System Temp 12'],
            ['sensor_temp_13', 'System Temp 13'],
            ['sensor_temp_14', 'System Temp 14'],
            ['sensor_temp_15', 'System Temp 15'],
            ['sensor_temp_16', 'System Temp 16'],
            ['sensor_temp_17', 'System Temp 17'],
            ['sensor_temp_18', 'System Temp 18'],
            ['sensor_temp_19', 'System Temp 19'],
            ['sensor_temp_20', 'System Temp 20'],
            ['sensor_temp_21', 'System Temp 21'],
            ['sensor_temp_22', 'System Temp 22'],
            ['sensor_temp_23', 'System Temp 23'],
            ['sensor_temp_24', 'System Temp 24'],
            ['sensor_temp_25', 'System Temp 25'],
            ['sensor_temp_26', 'System Temp 26'],
            ['sensor_temp_27', 'System Temp 27'],
            ['sensor_temp_28', 'System Temp 28'],
            ['sensor_temp_29', 'System Temp 29'],
        )
    }


    TEMP_SENSOR__TSL2561_GAIN_choices = (
        ('0', '[0] Low - 1x'),
        ('1', '[1] High - 16x'),
    )


    TEMP_SENSOR__TSL2561_INT_choices = (
        ('0', '[0] 13.7ms'),
        ('1', '[1] 101ms (default)'),
        ('2', '[2] 402ms '),
    )


    TEMP_SENSOR__SHT4X_MODE_choices = (
        ('NOHEAT_HIGHPRECISION', '[0xFD] No Heater - High Precision'),
        ('NOHEAT_MEDPRECISION', '[0xF6] No Heater - Medium Precision'),
        ('NOHEAT_LOWPRECISION', '[0xE0] No Heater - Low Precision'),
        ('HIGHHEAT_1S', '[0x39] High Heat - 1s'),
        ('HIGHHEAT_100MS', '[0x32] High Heat - 0.1s'),
        ('MEDHEAT_1S', '[0x2F] Medium Heat - 1s'),
        ('MEDHEAT_100MS', '[0x24] Medium Heat - 0.1s'),
        ('LOWHEAT_1S', '[0x1E] Low Heat - 1s'),
        ('LOWHEAT_100MS', '[0x15] Low Heat - 0.1s'),
    )

    TEMP_SENSOR__SI7021_HEATER_LEVEL_choices = (
        ('-1', 'Off'),
        ('0', '0 - 3 mA'),
        ('1', '1 - 9 mA'),
        ('2', '2 - 15 mA'),
        ('3', '3 - 21 mA'),
        ('4', '4 - 27 mA'),
        ('5', '5 - 33 mA'),
        ('6', '6 - 40 mA'),
        ('7', '7 - 46 mA'),
        ('8', '8 - 52 mA'),
        ('9', '9 - 58 mA'),
        ('10', '10 - 64 mA'),
        ('11', '11 - 70 mA'),
        ('12', '12 - 76 mA'),
        ('13', '13 - 82 mA'),
        ('14', '14 - 88 mA'),
        ('15', '15 - 94 mA'),
    )

    TEMP_SENSOR__HDC302X_HEATER_choices = (
        ('OFF', '[OFF] - Off'),
        ('QUARTER_POWER', '[QUARTER_POWER] - 25%'),
        ('HALF_POWER', '[HALF_POWER] - 50%'),
        ('FULL_POWER', '[FULL_POWER] - 100%'),
    )

    TEMP_SENSOR__TSL2591_GAIN_choices = (
        ('GAIN_LOW', '[0] Low - 1x'),
        ('GAIN_MED', '[16] Medium - 25x (default)'),
        ('GAIN_HIGH', '[32] High - 428x'),
        ('GAIN_MAX', '[48] Maximum - 9876x'),
    )


    TEMP_SENSOR__TSL2591_INT_choices = (
        ('INTEGRATIONTIME_100MS', '[0] 100ms (default)'),
        ('INTEGRATIONTIME_200MS', '[1] 200ms'),
        ('INTEGRATIONTIME_300MS', '[2] 300ms'),
        ('INTEGRATIONTIME_400MS', '[3] 400ms'),
        ('INTEGRATIONTIME_500MS', '[4] 500ms'),
        ('INTEGRATIONTIME_600MS', '[5] 600ms'),
    )


    TEMP_SENSOR__VEML7700_GAIN_choices = (
        ('ALS_GAIN_1_8', '[2] Low - 1/8x'),
        ('ALS_GAIN_1_4', '[3] Medium - 1/4x'),
        ('ALS_GAIN_1', '[0] High - 1x'),
        ('ALS_GAIN_2', '[1] Maximum - 2x'),
    )

    TEMP_SENSOR__VEML7700_INT_choices = (
        ('ALS_25MS', '[12] 25ms)'),
        ('ALS_50MS', '[8] 50ms)'),
        ('ALS_100MS', '[0] 100ms (default)'),
        ('ALS_200MS', '[1] 200ms'),
        ('ALS_400MS', '[2] 400ms'),
        ('ALS_800MS', '[3] 800ms)'),
    )


    TEMP_SENSOR__SI1145_GAIN_choices = (
        ('GAIN_ADC_CLOCK_DIV_1', '[0] - 1x (default)'),
        ('GAIN_ADC_CLOCK_DIV_2', '[1] - 2x'),
        ('GAIN_ADC_CLOCK_DIV_4', '[2] - 4x'),
        ('GAIN_ADC_CLOCK_DIV_8', '[3] - 8x'),
        ('GAIN_ADC_CLOCK_DIV_16', '[4] - 16x'),
        ('GAIN_ADC_CLOCK_DIV_32', '[5] - 32x'),
        ('GAIN_ADC_CLOCK_DIV_64', '[6] - 64x'),
        ('GAIN_ADC_CLOCK_DIV_128', '[7] - 128x'),
    )

    TEMP_SENSOR__LTR390_GAIN_choices = (
        ('GAIN_1X', '[0] - 1x (default)'),
        ('GAIN_3X', '[1] - 3x'),
        ('GAIN_6X', '[2] - 6x'),
        ('GAIN_9X', '[3] - 9x'),
        ('GAIN_18X', '[4] - 18x'),
    )


    ENCRYPT_PASSWORDS                = BooleanField('Encrypt Passwords')
    CAMERA_INTERFACE                 = SelectField('Camera Interface', choices=CAMERA_INTERFACE_choices, validators=[DataRequired(), CAMERA_INTERFACE_validator])
    INDI_SERVER                      = StringField('INDI Server', validators=[DataRequired(), INDI_SERVER_validator])
    INDI_PORT                        = IntegerField('INDI port', validators=[DataRequired(), INDI_PORT_validator])
    INDI_CAMERA_NAME                 = StringField('INDI Camera Name', validators=[INDI_CAMERA_NAME_validator])
    OWNER                            = StringField('Owner', validators=[OWNER_validator])
    LENS_NAME                        = StringField('Lens Name', validators=[LENS_NAME_validator])
    LENS_FOCAL_LENGTH                = FloatField('Focal Length', validators=[LENS_FOCAL_LENGTH_validator])
    LENS_FOCAL_RATIO                 = FloatField('Focal Ratio', validators=[LENS_FOCAL_RATIO_validator])
    LENS_IMAGE_CIRCLE                = IntegerField('Image Circle', validators=[LENS_IMAGE_CIRCLE_validator])
    LENS_OFFSET_X                    = IntegerField('X Offset', validators=[LENS_OFFSET_validator])
    LENS_OFFSET_Y                    = IntegerField('Y Offset', validators=[LENS_OFFSET_validator])
    LENS_ALTITUDE                    = FloatField('Altitude', validators=[LENS_ALTITUDE_validator])
    LENS_AZIMUTH                     = FloatField('Azimuth', validators=[LENS_AZIMUTH_validator])
    CCD_CONFIG__NIGHT__GAIN          = IntegerField('Night Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__NIGHT__BINNING       = IntegerField('Night Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__MOONMODE__GAIN       = IntegerField('Moon Mode Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__MOONMODE__BINNING    = IntegerField('Moon Mode Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__DAY__GAIN            = IntegerField('Daytime Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__DAY__BINNING         = IntegerField('Daytime Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_EXPOSURE_MAX                 = FloatField('Max Exposure', validators=[DataRequired(), CCD_EXPOSURE_MAX_validator])
    CCD_EXPOSURE_DEF                 = FloatField('Default Exposure', validators=[CCD_EXPOSURE_DEF_validator])
    CCD_EXPOSURE_MIN                 = FloatField('Min Exposure (Night)', validators=[CCD_EXPOSURE_MIN_validator])
    CCD_EXPOSURE_MIN_DAY             = FloatField('Min Exposure (Day)', validators=[CCD_EXPOSURE_MIN_validator])
    CCD_BIT_DEPTH                    = SelectField('Camera Bit Depth', choices=CCD_BIT_DEPTH_choices, validators=[CCD_BIT_DEPTH_validator])
    EXPOSURE_PERIOD                  = FloatField('Exposure Period (Night)', validators=[DataRequired(), EXPOSURE_PERIOD_validator])
    EXPOSURE_PERIOD_DAY              = FloatField('Exposure Period (Day)', validators=[DataRequired(), EXPOSURE_PERIOD_DAY_validator])
    FOCUS_MODE                       = BooleanField('Focus Mode')
    FOCUS_DELAY                      = FloatField('Focus Delay', validators=[DataRequired(), FOCUS_DELAY_validator])
    CFA_PATTERN                      = SelectField('Bayer Pattern', choices=CFA_PATTERN_choices, validators=[CFA_PATTERN_validator])
    USE_NIGHT_COLOR                  = BooleanField('Use Night Color Settings')
    SCNR_ALGORITHM                   = SelectField('SCNR (Night)', choices=SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    SCNR_ALGORITHM_DAY               = SelectField('SCNR (Day)', choices=SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    WBR_FACTOR                       = FloatField('Red Balance Factor (Night)', validators=[WB_FACTOR_validator])
    WBG_FACTOR                       = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator])
    WBB_FACTOR                       = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator])
    WBR_FACTOR_DAY                   = FloatField('Red Balance Factor (Day)', validators=[WB_FACTOR_validator])
    WBG_FACTOR_DAY                   = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator])
    WBB_FACTOR_DAY                   = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator])
    AUTO_WB                          = BooleanField('Auto White Balance (Night)')
    AUTO_WB_DAY                      = BooleanField('Auto White Balance (Day)')
    SATURATION_FACTOR                = FloatField('Saturation Factor (Night)', validators=[SATURATION_FACTOR_validator])
    SATURATION_FACTOR_DAY            = FloatField('Saturation Factor (Day)', validators=[SATURATION_FACTOR_validator])
    GAMMA_CORRECTION                 = FloatField('Gamma Correction (Night)', validators=[GAMMA_CORRECTION_validator])
    GAMMA_CORRECTION_DAY             = FloatField('Gamma Correction (Day)', validators=[GAMMA_CORRECTION_validator])
    CCD_COOLING                      = BooleanField('CCD Cooling')
    CCD_TEMP                         = FloatField('Target CCD Temp', validators=[CCD_TEMP_validator])
    TEMP_DISPLAY                     = SelectField('Temperature Display', choices=TEMP_DISPLAY_choices, validators=[DataRequired(), TEMP_DISPLAY_validator])
    PRESSURE_DISPLAY                 = SelectField('Pressure Display', choices=PRESSURE_DISPLAY_choices, validators=[DataRequired(), PRESSURE_DISPLAY_validator])
    WINDSPEED_DISPLAY                = SelectField('Wind Speed Display', choices=WINDSPEED_DISPLAY_choices, validators=[DataRequired(), WINDSPEED_DISPLAY_validator])
    CCD_TEMP_SCRIPT                  = StringField('External Temperature Script', validators=[CCD_TEMP_SCRIPT_validator])
    GPS_ENABLE                       = BooleanField('GPS Enable')
    TARGET_ADU                       = IntegerField('Target ADU (night)', validators=[DataRequired(), TARGET_ADU_validator])
    TARGET_ADU_DAY                   = IntegerField('Target ADU (day)', validators=[DataRequired(), TARGET_ADU_DAY_validator])
    TARGET_ADU_DEV                   = IntegerField('Target ADU Deviation (night)', validators=[DataRequired(), TARGET_ADU_DEV_validator])
    TARGET_ADU_DEV_DAY               = IntegerField('Target ADU Deviation (day)', validators=[DataRequired(), TARGET_ADU_DEV_DAY_validator])
    ADU_ROI_X1                       = IntegerField('ADU ROI x1', validators=[ADU_ROI_validator])
    ADU_ROI_Y1                       = IntegerField('ADU ROI y1', validators=[ADU_ROI_validator])
    ADU_ROI_X2                       = IntegerField('ADU ROI x2', validators=[ADU_ROI_validator])
    ADU_ROI_Y2                       = IntegerField('ADU ROI y2', validators=[ADU_ROI_validator])
    ADU_FOV_DIV                      = SelectField('ADU FoV', choices=ADU_FOV_DIV_choices, validators=[ADU_FOV_DIV_validator])
    DETECT_STARS                     = BooleanField('Star Detection')
    DETECT_STARS_THOLD               = FloatField('Star Detection Threshold', validators=[DataRequired(), DETECT_STARS_THOLD_validator])
    DETECT_METEORS                   = BooleanField('Meteor Detection')
    DETECT_MASK                      = StringField('Detection Mask', validators=[DETECT_MASK_validator])
    DETECT_DRAW                      = BooleanField('Mark Detections on Image')
    LOGO_OVERLAY                     = StringField('Logo Overlay', validators=[LOGO_OVERLAY_validator])
    SQM_ROI_X1                       = IntegerField('SQM ROI x1', validators=[SQM_ROI_validator])
    SQM_ROI_Y1                       = IntegerField('SQM ROI y1', validators=[SQM_ROI_validator])
    SQM_ROI_X2                       = IntegerField('SQM ROI x2', validators=[SQM_ROI_validator])
    SQM_ROI_Y2                       = IntegerField('SQM ROI y2', validators=[SQM_ROI_validator])
    SQM_FOV_DIV                      = SelectField('SQM FoV', choices=SQM_FOV_DIV_choices, validators=[SQM_FOV_DIV_validator])
    HEALTHCHECK__DISK_USAGE          = FloatField('Disk Usage Percentage', validators=[DataRequired(), HEALTHCHECK__DISK_USAGE_validator])
    HEALTHCHECK__SWAP_USAGE          = FloatField('Swap Usage Percentage', validators=[DataRequired(), HEALTHCHECK__SWAP_USAGE_validator])
    LOCATION_NAME                    = StringField('Location', validators=[LOCATION_NAME_validator])
    LOCATION_LATITUDE                = FloatField('Latitude', validators=[LOCATION_LATITUDE_validator])
    LOCATION_LONGITUDE               = FloatField('Longitude', validators=[LOCATION_LONGITUDE_validator])
    LOCATION_ELEVATION               = IntegerField('Elevation', validators=[LOCATION_ELEVATION_validator])
    TIMELAPSE_ENABLE                 = BooleanField('Enable Timelapse Creation')
    TIMELAPSE_SKIP_FRAMES            = IntegerField('Timelapse Skip Frames', validators=[TIMELAPSE_SKIP_FRAMES_validator])
    TIMELAPSE__PRE_PROCESSOR         = SelectField('Timelapse Processing', choices=TIMELAPSE__PRE_PROCESSOR_choices, validators=[TIMELAPSE__PRE_PROCESSOR_validator])
    TIMELAPSE__IMAGE_CIRCLE          = IntegerField('Image Circle Diameter', validators=[DataRequired(), TIMELAPSE__IMAGE_CIRCLE_validator])
    TIMELAPSE__KEOGRAM_RATIO         = FloatField('Keogram Ratio', validators=[DataRequired(), TIMELAPSE__KEOGRAM_RATIO_validator])
    TIMELAPSE__PRE_SCALE             = IntegerField('Pre-Scale Images', validators=[DataRequired(), TIMELAPSE__PRE_SCALE_validator])
    TIMELAPSE__FFMPEG_REPORT         = BooleanField('Generate FFMPEG debug report')
    CAPTURE_PAUSE                    = BooleanField('Pause Capture')
    DAYTIME_CAPTURE                  = BooleanField('Daytime Capture')
    DAYTIME_CAPTURE_SAVE             = BooleanField('Daytime Save Images')
    DAYTIME_TIMELAPSE                = BooleanField('Daytime Timelapse')
    DAYTIME_CONTRAST_ENHANCE         = BooleanField('Daytime Contrast Enhance')
    NIGHT_CONTRAST_ENHANCE           = BooleanField('Night time Contrast Enhance')
    CONTRAST_ENHANCE_16BIT           = BooleanField('16-bit Contrast Enhance')
    CLAHE_CLIPLIMIT                  = FloatField('CLAHE Clip Limit', validators=[CLAHE_CLIPLIMIT_validator])
    CLAHE_GRIDSIZE                   = IntegerField('CLAHE Grid Size', validators=[CLAHE_GRIDSIZE_validator])
    NIGHT_SUN_ALT_DEG                = FloatField('Sun altitude', validators=[NIGHT_SUN_ALT_DEG_validator])
    NIGHT_MOONMODE_ALT_DEG           = FloatField('Moonmode Moon Altitude', validators=[NIGHT_MOONMODE_ALT_DEG_validator])
    NIGHT_MOONMODE_PHASE             = FloatField('Moonmode Moon Phase', validators=[NIGHT_MOONMODE_PHASE_validator])
    WEB_STATUS_TEMPLATE              = TextAreaField('Status Template', validators=[DataRequired(), WEB_STATUS_TEMPLATE_validator])
    WEB_EXTRA_TEXT                   = StringField('Extra HTML Info File', validators=[WEB_EXTRA_TEXT_validator])
    WEB_NONLOCAL_IMAGES              = BooleanField('Non-Local Images')
    WEB_LOCAL_IMAGES_ADMIN           = BooleanField('Local Images from Admin Networks')
    IMAGE_STRETCH__CLASSNAME         = SelectField('Stretch Function', choices=IMAGE_STRETCH__CLASSNAME_choices, validators=[IMAGE_STRETCH__CLASSNAME_validator])
    IMAGE_STRETCH__MODE1_GAMMA       = FloatField('StdDev Cutoff - Stretching Gamma', validators=[IMAGE_STRETCH__MODE1_GAMMA_validator])
    IMAGE_STRETCH__MODE1_STDDEVS     = FloatField('StdDev Cutoff - Stretching Std Deviations', validators=[DataRequired(), IMAGE_STRETCH__MODE1_STDDEVS_validator])
    IMAGE_STRETCH__MODE2_SHADOWS     = FloatField('MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE2_SHADOWS_validator])
    IMAGE_STRETCH__MODE2_MIDTONES    = FloatField('MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE2_MIDTONES_validator])
    IMAGE_STRETCH__MODE2_HIGHLIGHTS  = FloatField('MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator])
    IMAGE_STRETCH__SPLIT             = BooleanField('Stretching split screen')
    IMAGE_STRETCH__MOONMODE          = BooleanField('Moon Mode Stretching')
    IMAGE_STRETCH__DAYTIME           = BooleanField('Daytime Stretching')
    KEOGRAM_ANGLE                    = FloatField('Keogram Rotation Angle', validators=[KEOGRAM_ANGLE_validator])
    KEOGRAM_H_SCALE                  = IntegerField('Keogram Horizontal Scaling', validators=[DataRequired(), KEOGRAM_H_SCALE_validator])
    KEOGRAM_V_SCALE                  = IntegerField('Keogram Vertical Scaling', validators=[DataRequired(), KEOGRAM_V_SCALE_validator])
    KEOGRAM_CROP_TOP                 = IntegerField('Keogram Crop Top (%)', validators=[KEOGRAM_CROP_TOP_validator])
    KEOGRAM_CROP_BOTTOM              = IntegerField('Keogram Crop Bottom (%)', validators=[KEOGRAM_CROP_BOTTOM_validator])
    KEOGRAM_LABEL                    = BooleanField('Label Keogram')
    LONGTERM_KEOGRAM__ENABLE         = BooleanField('Enable Long Term Keogram')
    LONGTERM_KEOGRAM__OFFSET_X       = IntegerField('X Offset', validators=[LONGTERM_KEOGRAM__OFFSET_X_validator])
    LONGTERM_KEOGRAM__OFFSET_Y       = IntegerField('Y Offset', validators=[LONGTERM_KEOGRAM__OFFSET_Y_validator])
    REALTIME_KEOGRAM__MAX_ENTRIES    = IntegerField('Realtime Keogram Max Entries', validators=[REALTIME_KEOGRAM__MAX_ENTRIES_validator])
    REALTIME_KEOGRAM__SAVE_INTERVAL  = IntegerField('Save Interval', validators=[REALTIME_KEOGRAM__SAVE_INTERVAL_validator])
    STARTRAILS_SUN_ALT_THOLD         = FloatField('Star Trails Max Sun Altitude', validators=[DataRequired(), STARTRAILS_SUN_ALT_THOLD_validator])
    STARTRAILS_MOONMODE_THOLD        = BooleanField('Star Trails Exclude Moon Mode')
    STARTRAILS_MOON_ALT_THOLD        = FloatField('Custom Max Moon Altitude', validators=[DataRequired(), STARTRAILS_MOON_ALT_THOLD_validator])
    STARTRAILS_MOON_PHASE_THOLD      = FloatField('Custom Max Moon Phase', validators=[DataRequired(), STARTRAILS_MOON_PHASE_THOLD_validator])
    STARTRAILS_MAX_ADU               = IntegerField('Star Trails Max ADU', validators=[DataRequired(), STARTRAILS_MAX_ADU_validator])
    STARTRAILS_MASK_THOLD            = IntegerField('Star Trails Mask Threshold ADU', validators=[DataRequired(), STARTRAILS_MASK_THOLD_validator])
    STARTRAILS_PIXEL_THOLD           = FloatField('Star Trails Pixel Threshold', validators=[STARTRAILS_PIXEL_THOLD_validator])
    STARTRAILS_MIN_STARS             = IntegerField('Star Trails Minimum Stars', validators=[STARTRAILS_MIN_STARS_validator])
    STARTRAILS_TIMELAPSE             = BooleanField('Star Trails Timelapse')
    STARTRAILS_TIMELAPSE_MINFRAMES   = IntegerField('Star Trails Timelapse Minimum Frames', validators=[DataRequired(), STARTRAILS_TIMELAPSE_MINFRAMES_validator])
    STARTRAILS_USE_DB_DATA           = BooleanField('Star Trails Use Existing Data')
    IMAGE_CALIBRATE_DARK             = BooleanField('Apply Dark Calibration Frames')
    IMAGE_CALIBRATE_BPM              = BooleanField('Apply Bad Pixel Map Frames')
    IMAGE_SAVE_FITS_PRE_DARK         = BooleanField('Save FITS Pre-Calibration')
    IMAGE_EXIF_PRIVACY               = BooleanField('Enable EXIF Privacy')
    IMAGE_FILE_TYPE                  = SelectField('Image file type', choices=IMAGE_FILE_TYPE_choices, validators=[DataRequired(), IMAGE_FILE_TYPE_validator])
    IMAGE_FILE_COMPRESSION__JPG      = IntegerField('JPEG Quality', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__JPG_validator])
    IMAGE_FILE_COMPRESSION__PNG      = IntegerField('PNG Compression', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__PNG_validator])
    IMAGE_FILE_COMPRESSION__TIF      = StringField('TIFF Compression', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    IMAGE_FOLDER                     = StringField('Image folder', validators=[DataRequired(), IMAGE_FOLDER_validator])
    IMAGE_LABEL_TEMPLATE             = TextAreaField('Label Template', validators=[DataRequired(), IMAGE_LABEL_TEMPLATE_validator])
    IMAGE_EXTRA_TEXT                 = StringField('Extra Image Text File', validators=[IMAGE_EXTRA_TEXT_validator])
    IMAGE_ROTATE                     = SelectField('Rotate Image', choices=IMAGE_ROTATE_choices, validators=[IMAGE_ROTATE_validator])
    IMAGE_ROTATE_ANGLE               = IntegerField('Rotation Angle', validators=[IMAGE_ROTATE_ANGLE_validator])
    IMAGE_ROTATE_KEEP_SIZE           = BooleanField('Maintain Size After Rotation')
    #IMAGE_ROTATE_WITH_OFFSET         = BooleanField('Use Offsets')
    IMAGE_FLIP_V                     = BooleanField('Flip Image Vertically')
    IMAGE_FLIP_H                     = BooleanField('Flip Image Horizontally')
    IMAGE_SCALE                      = IntegerField('Image Scaling', validators=[DataRequired(), IMAGE_SCALE_validator])
    IMAGE_CIRCLE_MASK__ENABLE        = BooleanField('Enable Image Circle Mask')
    IMAGE_CIRCLE_MASK__DIAMETER      = IntegerField('Mask Diameter', validators=[DataRequired(), IMAGE_CIRCLE_MASK__DIAMETER_validator])
    IMAGE_CIRCLE_MASK__OFFSET_X      = IntegerField('Mask X Offset', validators=[IMAGE_CIRCLE_MASK__OFFSET_X_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    IMAGE_CIRCLE_MASK__OFFSET_Y      = IntegerField('Mask Y Offset', validators=[IMAGE_CIRCLE_MASK__OFFSET_Y_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    IMAGE_CIRCLE_MASK__BLUR          = IntegerField('Mask Blur', validators=[IMAGE_CIRCLE_MASK__BLUR_validator])
    IMAGE_CIRCLE_MASK__OPACITY       = IntegerField('Mask Opacity %', validators=[IMAGE_CIRCLE_MASK__OPACITY_validator])
    IMAGE_CIRCLE_MASK__OUTLINE       = BooleanField('Mask Outline')
    IMAGE_CROP_ROI_X1                = IntegerField('Image Crop ROI x1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y1                = IntegerField('Image Crop ROI y1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_X2                = IntegerField('Image Crop ROI x2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y2                = IntegerField('Image Crop ROI y2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_QUEUE_MAX                  = IntegerField('Image Queue Maximum', validators=[IMAGE_QUEUE_MAX_validator])
    IMAGE_QUEUE_MIN                  = IntegerField('Image Queue Minimum', validators=[IMAGE_QUEUE_MIN_validator])
    IMAGE_QUEUE_BACKOFF              = FloatField('Image Queue Backoff Multiplier', validators=[IMAGE_QUEUE_BACKOFF_validator])
    FISH2PANO__ENABLE                = BooleanField('Enable Fisheye to Panoramic')
    FISH2PANO__DIAMETER              = IntegerField('Diameter', validators=[DataRequired(), FISH2PANO__DIAMETER_validator])
    FISH2PANO__OFFSET_X              = IntegerField('X Offset', validators=[FISH2PANO__OFFSET_X_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    FISH2PANO__OFFSET_Y              = IntegerField('Y Offset', validators=[FISH2PANO__OFFSET_Y_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    FISH2PANO__ROTATE_ANGLE          = IntegerField('Rotation Angle', validators=[FISH2PANO__ROTATE_ANGLE_validator])
    FISH2PANO__SCALE                 = FloatField('Scale', validators=[FISH2PANO__SCALE_validator])
    FISH2PANO__MODULUS               = IntegerField('Modulus', validators=[DataRequired(), FISH2PANO__MODULUS_validator])
    FISH2PANO__FLIP_H                = BooleanField('Flip Horizontally')
    FISH2PANO__ENABLE_CARDINAL_DIRS  = BooleanField('Fisheye Cardinal Directions')
    FISH2PANO__DIRS_OFFSET_BOTTOM    = IntegerField('Label Bottom Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    FISH2PANO__OPENCV_FONT_SCALE     = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    FISH2PANO__PIL_FONT_SIZE         = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    IMAGE_SAVE_FITS                  = BooleanField('Save FITS data')
    NIGHT_GRAYSCALE                  = BooleanField('Save in Grayscale at Night')
    DAYTIME_GRAYSCALE                = BooleanField('Save in Grayscale during Day')
    MOON_OVERLAY__ENABLE             = BooleanField('Enable Moon Overlay')
    MOON_OVERLAY__X                  = IntegerField('X', validators=[MOON_OVERLAY__X_validator])
    MOON_OVERLAY__Y                  = IntegerField('Y', validators=[MOON_OVERLAY__Y_validator])
    MOON_OVERLAY__SCALE              = FloatField('Overlay Scale', validators=[DataRequired(), MOON_OVERLAY__SCALE_validator])
    MOON_OVERLAY__DARK_SIDE_SCALE    = FloatField('Dark Side Brightness', validators=[MOON_OVERLAY__DARK_SIDE_SCALE_validator])
    MOON_OVERLAY__FLIP_V             = BooleanField('Flip Vertically')
    MOON_OVERLAY__FLIP_H             = BooleanField('Flip Horizontally')
    LIGHTGRAPH_OVERLAY__ENABLE       = BooleanField('Enable Lightgraph Overlay')
    LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT = IntegerField('Lightgraph Height', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator])
    LIGHTGRAPH_OVERLAY__GRAPH_BORDER = IntegerField('Lightgraph Border', validators=[LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator])
    LIGHTGRAPH_OVERLAY__Y            = IntegerField('Y', validators=[LIGHTGRAPH_OVERLAY__Y_validator])
    LIGHTGRAPH_OVERLAY__OFFSET_X     = IntegerField('X Offset', validators=[LIGHTGRAPH_OVERLAY__OFFSET_X_validator])
    LIGHTGRAPH_OVERLAY__SCALE        = FloatField('Scale', validators=[LIGHTGRAPH_OVERLAY__SCALE_validator])
    LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE = IntegerField('Time Marker Size', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator])
    LIGHTGRAPH_OVERLAY__DAY_COLOR    = StringField('Day Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__DUSK_COLOR   = StringField('Dusk/Dawn Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__NIGHT_COLOR  = StringField('Night Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__HOUR_COLOR   = StringField('Hour Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__BORDER_COLOR = StringField('Border Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__NOW_COLOR    = StringField('Time Marker Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__FONT_COLOR   = StringField('Font Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__OPACITY      = IntegerField('Opacity ', validators=[LIGHTGRAPH_OVERLAY__OPACITY_validator])
    LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE = IntegerField('Font Size (Pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    LIGHTGRAPH_OVERLAY__LABEL        = BooleanField('Lightgraph Label')
    LIGHTGRAPH_OVERLAY__HOUR_LINES   = BooleanField('Lightgraph Hour Lines')
    IMAGE_EXPORT_RAW                 = SelectField('Export RAW image type', choices=IMAGE_EXPORT_RAW_choices, validators=[IMAGE_EXPORT_RAW_validator])
    IMAGE_EXPORT_FOLDER              = StringField('Export RAW folder', validators=[DataRequired(), IMAGE_EXPORT_FOLDER_validator])
    IMAGE_EXPORT_FLIP_V              = BooleanField('Flip RAW Vertically')
    IMAGE_EXPORT_FLIP_H              = BooleanField('Flip RAW Horizontally')
    IMAGE_STACK_METHOD               = SelectField('Image stacking method', choices=IMAGE_STACK_METHOD_choices, validators=[DataRequired(), IMAGE_STACK_METHOD_validator])
    IMAGE_STACK_COUNT                = SelectField('Stack count', choices=IMAGE_STACK_COUNT_choices, validators=[DataRequired(), IMAGE_STACK_COUNT_validator])
    IMAGE_STACK_ALIGN                = BooleanField('Register images')
    IMAGE_ALIGN_DETECTSIGMA          = IntegerField('Alignment sensitivity', validators=[DataRequired(), IMAGE_ALIGN_DETECTSIGMA_validator])
    IMAGE_ALIGN_POINTS               = IntegerField('Alignment points', validators=[DataRequired(), IMAGE_ALIGN_POINTS_validator])
    IMAGE_ALIGN_SOURCEMINAREA        = IntegerField('Minimum point area', validators=[DataRequired(), IMAGE_ALIGN_SOURCEMINAREA_validator])
    IMAGE_STACK_SPLIT                = BooleanField('Stack split screen')
    THUMBNAILS__IMAGES_AUTO          = BooleanField('Auto Generate Image Thumbnails')
    IMAGE_EXPIRE_DAYS                = IntegerField('Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    IMAGE_RAW_EXPIRE_DAYS            = IntegerField('RAW Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    IMAGE_FITS_EXPIRE_DAYS           = IntegerField('FITS Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    TIMELAPSE_EXPIRE_DAYS            = IntegerField('Timelapse expiration (days)', validators=[DataRequired(), TIMELAPSE_EXPIRE_DAYS_validator])
    TIMELAPSE_OVERWRITE              = BooleanField('Allow Overwrite Existing Timelapses')
    FFMPEG_FRAMERATE                 = IntegerField('FFMPEG Framerate', validators=[DataRequired(), FFMPEG_FRAMERATE_validator])
    FFMPEG_BITRATE                   = StringField('FFMPEG Bitrate', validators=[DataRequired(), FFMPEG_BITRATE_validator])
    FFMPEG_VFSCALE                   = SelectField('FFMPEG Scaling', choices=FFMPEG_VFSCALE_choices, validators=[FFMPEG_VFSCALE_validator])
    FFMPEG_CODEC                     = SelectField('FFMPEG Codec', choices=FFMPEG_CODEC_choices, validators=[FFMPEG_CODEC_validator])
    FFMPEG_EXTRA_OPTIONS             = StringField('FFMPEG Extra Options', validators=[FFMPEG_EXTRA_OPTIONS_validator])
    IMAGE_LABEL_SYSTEM               = SelectField('Label Images', choices=IMAGE_LABEL_SYSTEM_choices, validators=[IMAGE_LABEL_SYSTEM_validator])
    TEXT_PROPERTIES__FONT_FACE       = SelectField('OpenCV Font', choices=TEXT_PROPERTIES__FONT_FACE_choices, validators=[DataRequired(), TEXT_PROPERTIES__FONT_FACE_validator])
    #TEXT_PROPERTIES__FONT_AA
    TEXT_PROPERTIES__FONT_SCALE      = FloatField('Font Scale', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    TEXT_PROPERTIES__FONT_THICKNESS  = IntegerField('Font Thickness', validators=[DataRequired(), TEXT_PROPERTIES__FONT_THICKNESS_validator])
    TEXT_PROPERTIES__FONT_OUTLINE    = BooleanField('Font Outline')
    TEXT_PROPERTIES__FONT_HEIGHT     = IntegerField('Text Height Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_HEIGHT_validator])
    TEXT_PROPERTIES__FONT_X          = IntegerField('Text X Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_X_validator])
    TEXT_PROPERTIES__FONT_Y          = IntegerField('Text Y Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_Y_validator])
    TEXT_PROPERTIES__FONT_COLOR      = StringField('Text Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    TEXT_PROPERTIES__PIL_FONT_FILE   = SelectField('Pillow Font', choices=TEXT_PROPERTIES__PIL_FONT_FILE_choices, validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_FILE_validator])
    TEXT_PROPERTIES__PIL_FONT_CUSTOM = StringField('Custom Font', validators=[TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator])
    TEXT_PROPERTIES__PIL_FONT_SIZE   = IntegerField('Font Size', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    CARDINAL_DIRS__ENABLE            = BooleanField('Enable Cardinal Directions')
    CARDINAL_DIRS__FONT_COLOR        = StringField('Text Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    CARDINAL_DIRS__SWAP_NS           = BooleanField('Swap North/South')
    CARDINAL_DIRS__SWAP_EW           = BooleanField('Swap East/West')
    CARDINAL_DIRS__CHAR_NORTH        = StringField('North Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_EAST         = StringField('East Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_WEST         = StringField('West Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_SOUTH        = StringField('South Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__DIAMETER          = IntegerField('Image Circle Diameter', validators=[CARDINAL_DIRS__DIAMETER_validator])
    CARDINAL_DIRS__OFFSET_X          = IntegerField('X Offset', validators=[CARDINAL_DIRS__CENTER_OFFSET_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    CARDINAL_DIRS__OFFSET_Y          = IntegerField('Y Offset', validators=[CARDINAL_DIRS__CENTER_OFFSET_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    CARDINAL_DIRS__OFFSET_TOP        = IntegerField('Top Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_LEFT       = IntegerField('Left Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_RIGHT      = IntegerField('Right Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_BOTTOM     = IntegerField('Bottom Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OPENCV_FONT_SCALE = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    CARDINAL_DIRS__PIL_FONT_SIZE     = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    CARDINAL_DIRS__OUTLINE_CIRCLE    = BooleanField('Image Circle Outline')
    ORB_PROPERTIES__MODE             = SelectField('Orb Mode', choices=ORB_PROPERTIES__MODE_choices, validators=[DataRequired(), ORB_PROPERTIES__MODE_validator])
    ORB_PROPERTIES__RADIUS           = IntegerField('Orb Radius', validators=[DataRequired(), ORB_PROPERTIES__RADIUS_validator])
    ORB_PROPERTIES__SUN_COLOR        = StringField('Sun Orb Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    ORB_PROPERTIES__MOON_COLOR       = StringField('Moon Orb Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    ORB_PROPERTIES__AZ_OFFSET        = FloatField('Azimuth Offset', validators=[ORB_PROPERTIES__AZ_OFFSET_validator])
    ORB_PROPERTIES__RETROGRADE       = BooleanField('Reverse Orb Motion')
    IMAGE_BORDER__TOP                = IntegerField('Image Border Top', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__LEFT               = IntegerField('Image Border Left', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__RIGHT              = IntegerField('Image Border Right', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__BOTTOM             = IntegerField('Image Border Bottom', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__COLOR              = StringField('Border Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    UPLOAD_WORKERS                   = IntegerField('Upload Workers', validators=[DataRequired(), UPLOAD_WORKERS_validator])
    FILETRANSFER__CLASSNAME          = SelectField('Protocol', choices=FILETRANSFER__CLASSNAME_choices, validators=[DataRequired(), FILETRANSFER__CLASSNAME_validator])
    FILETRANSFER__HOST               = StringField('Host', validators=[FILETRANSFER__HOST_validator])
    FILETRANSFER__PORT               = IntegerField('Port', validators=[FILETRANSFER__PORT_validator])
    FILETRANSFER__USERNAME           = StringField('Username', validators=[FILETRANSFER__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    FILETRANSFER__PASSWORD           = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[FILETRANSFER__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    FILETRANSFER__PRIVATE_KEY        = StringField('Private Key', validators=[FILETRANSFER__PRIVATE_KEY_validator])
    FILETRANSFER__PUBLIC_KEY         = StringField('Public Key', validators=[FILETRANSFER__PUBLIC_KEY_validator])
    FILETRANSFER__CONNECT_TIMEOUT    = FloatField('Connect Timeout', validators=[DataRequired(), FILETRANSFER__TIMEOUT_validator])
    FILETRANSFER__TIMEOUT            = FloatField('Read Timeout', validators=[DataRequired(), FILETRANSFER__TIMEOUT_validator])
    FILETRANSFER__CERT_BYPASS        = BooleanField('Disable Certificate Validation')
    FILETRANSFER__ATOMIC_TRANSFERS   = BooleanField('Atomic File Transfers')
    FILETRANSFER__FORCE_IPV4         = BooleanField('Force IPv4')
    FILETRANSFER__FORCE_IPV6         = BooleanField('Force IPv6')
    FILETRANSFER__LIBCURL_OPTIONS    = TextAreaField('PycURL Options', validators=[DataRequired(), FILETRANSFER__LIBCURL_OPTIONS_validator])
    FILETRANSFER__REMOTE_IMAGE_NAME        = StringField('Remote Image Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_IMAGE_FOLDER      = StringField('Remote Image Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_PANORAMA_NAME     = StringField('Remote Panorama Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_PANORAMA_FOLDER   = StringField('Remote Panorama Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_METADATA_NAME     = StringField('Remote Metadata Name', validators=[DataRequired(), FILETRANSFER__REMOTE_METADATA_NAME_validator])
    FILETRANSFER__REMOTE_METADATA_FOLDER   = StringField('Remote Metadata Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_RAW_NAME          = StringField('Remote RAW Image Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_RAW_FOLDER        = StringField('Remote RAW Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_FITS_NAME         = StringField('Remote FITS Image Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_FITS_FOLDER       = StringField('Remote FITS Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_VIDEO_NAME        = StringField('Remote Timelapse Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_VIDEO_FOLDER      = StringField('Remote Timelapse Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_MINI_VIDEO_NAME   = StringField('Remote Mini-Timelapse Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_MINI_VIDEO_FOLDER = StringField('Remote Mini-Timelapse Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_KEOGRAM_NAME      = StringField('Remote Keogram Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_KEOGRAM_FOLDER    = StringField('Remote Keogram Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_STARTRAIL_NAME    = StringField('Remote Star Trail Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_STARTRAIL_FOLDER  = StringField('Remote Star Trail Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_STARTRAIL_VIDEO_NAME   = StringField('Remote Star Trail Video Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_STARTRAIL_VIDEO_FOLDER = StringField('Remote Star Trail Video Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_PANORAMA_VIDEO_NAME    = StringField('Remote Panorama Video Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_PANORAMA_VIDEO_FOLDER  = StringField('Remote Panorama Video Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER = StringField('Remote EndOfNight Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__UPLOAD_IMAGE       = IntegerField('Transfer images', validators=[FILETRANSFER__UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_PANORAMA    = IntegerField('Transfer panoramas', validators=[FILETRANSFER__UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_METADATA    = BooleanField('Transfer metadata')
    FILETRANSFER__UPLOAD_RAW         = BooleanField('Transfer RAW')
    FILETRANSFER__UPLOAD_FITS        = BooleanField('Transfer FITS')
    FILETRANSFER__UPLOAD_VIDEO       = BooleanField('Transfer timelapses')
    FILETRANSFER__UPLOAD_MINI_VIDEO  = BooleanField('Transfer mini timelapses')
    FILETRANSFER__UPLOAD_KEOGRAM     = BooleanField('Transfer keograms')
    FILETRANSFER__UPLOAD_STARTRAIL   = BooleanField('Transfer star trails')
    FILETRANSFER__UPLOAD_STARTRAIL_VIDEO = BooleanField('Transfer star trail videos')
    FILETRANSFER__UPLOAD_PANORAMA_VIDEO  = BooleanField('Transfer panorama videos')
    FILETRANSFER__UPLOAD_ENDOFNIGHT  = BooleanField('Transfer AllSky EndOfNight data')
    S3UPLOAD__CLASSNAME              = SelectField('S3 Utility', choices=S3UPLOAD__CLASSNAME_choices, validators=[DataRequired(), S3UPLOAD__CLASSNAME_validator])
    S3UPLOAD__ENABLE                 = BooleanField('Enable S3 Uploading')
    S3UPLOAD__ACCESS_KEY             = StringField('Access Key', validators=[S3UPLOAD__ACCESS_KEY_validator])
    S3UPLOAD__SECRET_KEY             = PasswordField('Secret Key', widget=PasswordInput(hide_value=False), validators=[S3UPLOAD__SECRET_KEY_validator])
    S3UPLOAD__CREDS_FILE             = StringField('Credentials File', validators=[S3UPLOAD__CREDS_FILE_validator])
    S3UPLOAD__BUCKET                 = StringField('Bucket', validators=[DataRequired(), S3UPLOAD__BUCKET_validator])
    S3UPLOAD__REGION                 = StringField('Region', validators=[S3UPLOAD__REGION_validator])
    S3UPLOAD__NAMESPACE              = StringField('Namespace', validators=[S3UPLOAD__NAMESPACE_validator])
    S3UPLOAD__HOST                   = StringField('Host', validators=[DataRequired(), S3UPLOAD__HOST_validator])
    S3UPLOAD__PORT                   = IntegerField('Port', validators=[S3UPLOAD__PORT_validator])
    S3UPLOAD__CONNECT_TIMEOUT        = FloatField('Connect Timeout', validators=[DataRequired(), S3UPLOAD__TIMEOUT_validator])
    S3UPLOAD__TIMEOUT                = FloatField('Read Timeout', validators=[DataRequired(), S3UPLOAD__TIMEOUT_validator])
    S3UPLOAD__URL_TEMPLATE           = StringField('URL Template', validators=[DataRequired(), S3UPLOAD__URL_TEMPLATE_validator])
    S3UPLOAD__ACL                    = StringField('S3 ACL', validators=[S3UPLOAD__ACL_validator])
    S3UPLOAD__STORAGE_CLASS          = StringField('S3 Storage Class', validators=[S3UPLOAD__STORAGE_CLASS_validator])
    S3UPLOAD__TLS                    = BooleanField('Use TLS')
    S3UPLOAD__CERT_BYPASS            = BooleanField('Disable Certificate Validation')
    S3UPLOAD__UPLOAD_FITS            = BooleanField('Upload FITS files')
    S3UPLOAD__UPLOAD_RAW             = BooleanField('Upload RAW files')
    MQTTPUBLISH__ENABLE              = BooleanField('Enable MQTT Publishing')
    MQTTPUBLISH__TRANSPORT           = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    MQTTPUBLISH__HOST                = StringField('MQTT Host', validators=[MQTTPUBLISH__HOST_validator])
    MQTTPUBLISH__PORT                = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    MQTTPUBLISH__USERNAME            = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    MQTTPUBLISH__PASSWORD            = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    MQTTPUBLISH__BASE_TOPIC          = StringField('MQTT Base Topic', validators=[DataRequired(), MQTTPUBLISH__BASE_TOPIC_validator])
    MQTTPUBLISH__QOS                 = IntegerField('MQTT QoS', validators=[MQTTPUBLISH__QOS_validator])
    MQTTPUBLISH__TLS                 = BooleanField('Use TLS')
    MQTTPUBLISH__CERT_BYPASS         = BooleanField('Disable Certificate Validation')
    MQTTPUBLISH__PUBLISH_IMAGE       = BooleanField('Enable Image Publishing')
    SYNCAPI__ENABLE                  = BooleanField('Enable Sync API')
    SYNCAPI__BASEURL                 = StringField('URL', validators=[SYNCAPI__BASEURL_validator], render_kw={'autocomplete' : 'new-password'})  # prevent saving BASEURL as username
    SYNCAPI__USERNAME                = StringField('Username', validators=[SYNCAPI__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    SYNCAPI__APIKEY                  = PasswordField('API Key', widget=PasswordInput(hide_value=False), validators=[SYNCAPI__APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    SYNCAPI__CERT_BYPASS             = BooleanField('Disable Certificate Validation')
    SYNCAPI__POST_S3                 = BooleanField('Sync after S3 Upload')
    SYNCAPI__EMPTY_FILE              = BooleanField('Sync empty file')
    SYNCAPI__UPLOAD_IMAGE            = IntegerField('Transfer images', validators=[SYNCAPI__UPLOAD_IMAGE_validator])
    SYNCAPI__UPLOAD_PANORAMA         = IntegerField('Transfer panoramas', validators=[SYNCAPI__UPLOAD_IMAGE_validator])
    SYNCAPI__UPLOAD_VIDEO            = BooleanField('Transfer videos', render_kw={'disabled' : 'disabled'})
    SYNCAPI__CONNECT_TIMEOUT         = FloatField('Connect Timeout', validators=[DataRequired(), SYNCAPI__TIMEOUT_validator])
    SYNCAPI__TIMEOUT                 = FloatField('Read Timeout', validators=[DataRequired(), SYNCAPI__TIMEOUT_validator])
    YOUTUBE__ENABLE                  = BooleanField('Enable')
    YOUTUBE__SECRETS_FILE            = StringField('Client Secrets File', validators=[YOUTUBE__SECRETS_FILE_validator])
    YOUTUBE__PRIVACY_STATUS          = SelectField('Privacy Status', choices=YOUTUBE__PRIVACY_STATUS_choices, validators=[DataRequired(), YOUTUBE__PRIVACY_STATUS_validator])
    YOUTUBE__TITLE_TEMPLATE          = StringField('Title', validators=[DataRequired(), YOUTUBE__TITLE_TEMPLATE_validator])
    YOUTUBE__DESCRIPTION_TEMPLATE    = StringField('Description', validators=[YOUTUBE__DESCRIPTION_TEMPLATE_validator])
    YOUTUBE__CATEGORY                = IntegerField('Category ID', validators=[YOUTUBE__CATEGORY_validator])
    YOUTUBE__TAGS_STR                = StringField('Tags', validators=[YOUTUBE__TAGS_STR_validator])
    YOUTUBE__UPLOAD_VIDEO            = BooleanField('Auto-Upload Timelapses')
    YOUTUBE__UPLOAD_MINI_VIDEO       = BooleanField('Auto-Upload Mini Timelapses')
    YOUTUBE__UPLOAD_STARTRAIL_VIDEO  = BooleanField('Auto-Upload Star Trail Timelapses')
    YOUTUBE__UPLOAD_PANORAMA_VIDEO   = BooleanField('Auto-Upload Panorama Timelapses')
    YOUTUBE__REDIRECT_URI            = StringField('Detected Redirect URI', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    YOUTUBE__CREDS_STORED            = BooleanField('Credentials authorized', render_kw={'disabled' : 'disabled'})
    FITSHEADERS__0__KEY              = StringField('FITS Header 1', validators=[DataRequired(), FITSHEADER_KEY_validator])
    FITSHEADERS__0__VAL              = StringField('FITS Header 1 Value', validators=[])
    FITSHEADERS__1__KEY              = StringField('FITS Header 2', validators=[DataRequired(), FITSHEADER_KEY_validator])
    FITSHEADERS__1__VAL              = StringField('FITS Header 2 Value', validators=[])
    FITSHEADERS__2__KEY              = StringField('FITS Header 3', validators=[DataRequired(), FITSHEADER_KEY_validator])
    FITSHEADERS__2__VAL              = StringField('FITS Header 3 Value', validators=[])
    FITSHEADERS__3__KEY              = StringField('FITS Header 4', validators=[DataRequired(), FITSHEADER_KEY_validator])
    FITSHEADERS__3__VAL              = StringField('FITS Header 4 Value', validators=[])
    FITSHEADERS__4__KEY              = StringField('FITS Header 5', validators=[DataRequired(), FITSHEADER_KEY_validator])
    FITSHEADERS__4__VAL              = StringField('FITS Header 5 Value', validators=[])
    LIBCAMERA__IMAGE_FILE_TYPE       = SelectField('Night libcamera image type', choices=LIBCAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), LIBCAMERA__IMAGE_FILE_TYPE_validator])
    LIBCAMERA__IMAGE_FILE_TYPE_DAY   = SelectField('Day libcamera image type', choices=LIBCAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), LIBCAMERA__IMAGE_FILE_TYPE_validator])
    LIBCAMERA__AWB                   = SelectField('Night AWB', choices=LIBCAMERA__AWB_choices, validators=[DataRequired(), LIBCAMERA__AWB_validator])
    LIBCAMERA__AWB_DAY               = SelectField('Day AWB', choices=LIBCAMERA__AWB_choices, validators=[DataRequired(), LIBCAMERA__AWB_validator])
    LIBCAMERA__AWB_ENABLE            = BooleanField('Night Enable AWB')
    LIBCAMERA__AWB_ENABLE_DAY        = BooleanField('Day Enable AWB')
    LIBCAMERA__CAMERA_ID             = SelectField('Camera ID', choices=LIBCAMERA__CAMERA_ID_choices, validators=[LIBCAMERA__CAMERA_ID_validator])
    LIBCAMERA__EXTRA_OPTIONS         = StringField('Night libcamera extra options', validators=[LIBCAMERA__EXTRA_OPTIONS_validator])
    LIBCAMERA__EXTRA_OPTIONS_DAY     = StringField('Day libcamera extra options', validators=[LIBCAMERA__EXTRA_OPTIONS_validator])
    PYCURL_CAMERA__URL               = StringField('pyCurl Camera URL', validators=[PYCURL_CAMERA__URL_validator])
    PYCURL_CAMERA__IMAGE_FILE_TYPE   = SelectField('File Type', choices=PYCURL_CAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), PYCURL_CAMERA__IMAGE_FILE_TYPE_validator])
    PYCURL_CAMERA__USERNAME          = StringField('Username', validators=[PYCURL_CAMERA__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    PYCURL_CAMERA__PASSWORD          = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[PYCURL_CAMERA__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    ACCUM_CAMERA__SUB_EXPOSURE_MAX   = FloatField('Accumulator Max Sub-exposure', validators=[DataRequired(), ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator])
    ACCUM_CAMERA__EVEN_EXPOSURES     = BooleanField('Accumulator Even Exposures')
    FOCUSER__CLASSNAME               = SelectField('Focuser', choices=FOCUSER__CLASSNAME_choices, validators=[FOCUSER__CLASSNAME_validator])
    FOCUSER__GPIO_PIN_1              = StringField('GPIO Pin 1', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_2              = StringField('GPIO Pin 2', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_3              = StringField('GPIO Pin 3', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_4              = StringField('GPIO Pin 4', validators=[DEVICE_PIN_NAME_validator])
    DEW_HEATER__CLASSNAME            = SelectField('Dew Heater', choices=DEW_HEATER__CLASSNAME_choices, validators=[DEW_HEATER__CLASSNAME_validator])
    DEW_HEATER__ENABLE_DAY           = BooleanField('Enable Daytime')
    DEW_HEATER__PIN_1                = StringField('Pin', validators=[DEVICE_PIN_NAME_validator])
    DEW_HEATER__INVERT_OUTPUT        = BooleanField('Invert Output')
    DEW_HEATER__LEVEL_DEF            = IntegerField('Default Level', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__THOLD_ENABLE         = BooleanField('Enable Dew Heater Thresholds')
    DEW_HEATER__MANUAL_TARGET        = FloatField('Manual Target', validators=[DEW_HEATER__MANUAL_TARGET_validator])
    DEW_HEATER__TEMP_USER_VAR_SLOT   = SelectField('Temperature Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    DEW_HEATER__DEWPOINT_USER_VAR_SLOT = SelectField('Dew Point Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    DEW_HEATER__LEVEL_LOW            = IntegerField('Low Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__LEVEL_MED            = IntegerField('Medium Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__LEVEL_HIGH           = IntegerField('High Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__THOLD_DIFF_LOW       = IntegerField('Low Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    DEW_HEATER__THOLD_DIFF_MED       = IntegerField('Medium Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    DEW_HEATER__THOLD_DIFF_HIGH      = IntegerField('High Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    FAN__CLASSNAME                   = SelectField('Fan', choices=FAN__CLASSNAME_choices, validators=[FAN__CLASSNAME_validator])
    FAN__ENABLE_NIGHT                = BooleanField('Enable Night')
    FAN__PIN_1                       = StringField('Pin', validators=[DEVICE_PIN_NAME_validator])
    FAN__INVERT_OUTPUT               = BooleanField('Invert Output')
    FAN__LEVEL_DEF                   = IntegerField('Default Level', validators=[FAN__LEVEL_validator])
    FAN__THOLD_ENABLE                = BooleanField('Enable Fan Thresholds')
    FAN__TARGET                      = FloatField('Target Temp', validators=[FAN__TARGET_validator])
    FAN__TEMP_USER_VAR_SLOT          = SelectField('Temperature Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    FAN__LEVEL_LOW                   = IntegerField('Low Setting', validators=[FAN__LEVEL_validator])
    FAN__LEVEL_MED                   = IntegerField('Medium Setting', validators=[FAN__LEVEL_validator])
    FAN__LEVEL_HIGH                  = IntegerField('High Setting', validators=[FAN__LEVEL_validator])
    FAN__THOLD_DIFF_LOW              = IntegerField('Low Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    FAN__THOLD_DIFF_MED              = IntegerField('Medium Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    FAN__THOLD_DIFF_HIGH             = IntegerField('High Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    GENERIC_GPIO__A_CLASSNAME        = SelectField('GPIO', choices=GENERIC_GPIO__CLASSNAME_choices, validators=[GENERIC_GPIO__CLASSNAME_validator])
    GENERIC_GPIO__A_PIN_1            = StringField('Pin/Port', validators=[DEVICE_PIN_NAME_validator])
    GENERIC_GPIO__A_INVERT_OUTPUT    = BooleanField('Invert Output')
    TEMP_SENSOR__A_CLASSNAME         = SelectField('Sensor A', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__A_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__A_PIN_1             = StringField('Pin/Port', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__A_USER_VAR_SLOT     = SelectField('Sensor A Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__A_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), TEMP_SENSOR__I2C_ADDRESS_validator])
    TEMP_SENSOR__B_CLASSNAME         = SelectField('Sensor B', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__B_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__B_PIN_1             = StringField('Pin/Port', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__B_USER_VAR_SLOT     = SelectField('Sensor B Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__B_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), TEMP_SENSOR__I2C_ADDRESS_validator])
    TEMP_SENSOR__C_CLASSNAME         = SelectField('Sensor C', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__C_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__C_PIN_1             = StringField('Pin/Port', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__C_USER_VAR_SLOT     = SelectField('Sensor C Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__C_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), TEMP_SENSOR__I2C_ADDRESS_validator])
    TEMP_SENSOR__OPENWEATHERMAP_APIKEY = PasswordField('OpenWeatherMap API Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__OPENWEATHERMAP_APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__WUNDERGROUND_APIKEY = PasswordField('Weather Underground API Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__WUNDERGROUND_APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__ASTROSPHERIC_APIKEY = PasswordField('Astrospheric API Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__ASTROSPHERIC_APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__AMBIENTWEATHER_APIKEY         = PasswordField('Ambient Weather API Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__AMBIENTWEATHER_APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY = PasswordField('Ambient Weather Application Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__AMBIENTWEATHER_MACADDRESS     = StringField('Ambient Weather Device MAC Address', validators=[TEMP_SENSOR__MACADDRESS_validator])
    TEMP_SENSOR__ECOWITT_APIKEY         = PasswordField('Ecowitt API Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__ECOWITT_APIKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__ECOWITT_APPLICATIONKEY = PasswordField('Ecowitt Application Key', widget=PasswordInput(hide_value=False), validators=[TEMP_SENSOR__ECOWITT_APPLICATIONKEY_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__ECOWITT_MACADDRESS     = StringField('Ecowitt Device MAC Address', validators=[TEMP_SENSOR__MACADDRESS_validator])
    TEMP_SENSOR__MQTT_TRANSPORT      = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    TEMP_SENSOR__MQTT_TRANSPORT      = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    TEMP_SENSOR__MQTT_HOST           = StringField('MQTT Host', validators=[MQTTPUBLISH__HOST_validator])
    TEMP_SENSOR__MQTT_PORT           = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    TEMP_SENSOR__MQTT_USERNAME       = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__MQTT_PASSWORD       = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__MQTT_TLS            = BooleanField('Use TLS')
    TEMP_SENSOR__MQTT_CERT_BYPASS    = BooleanField('Disable Certificate Validation')
    TEMP_SENSOR__SHT3X_HEATER_NIGHT  = BooleanField('SHT3x Heater (Night)')
    TEMP_SENSOR__SHT3X_HEATER_DAY    = BooleanField('SHT3x Heater (Day)')
    TEMP_SENSOR__SHT4X_MODE_NIGHT    = SelectField('SHT4x Mode (Night)', choices=TEMP_SENSOR__SHT4X_MODE_choices, validators=[TEMP_SENSOR__SHT4X_MODE_validator])
    TEMP_SENSOR__SHT4X_MODE_DAY      = SelectField('SHT4x Mode (Day)', choices=TEMP_SENSOR__SHT4X_MODE_choices, validators=[TEMP_SENSOR__SHT4X_MODE_validator])
    TEMP_SENSOR__SI7021_HEATER_LEVEL_NIGHT = SelectField('SI7021 Heater Level (Night)', choices=TEMP_SENSOR__SI7021_HEATER_LEVEL_choices, validators=[TEMP_SENSOR__SI7021_HEATER_LEVEL_validator])
    TEMP_SENSOR__SI7021_HEATER_LEVEL_DAY   = SelectField('SI7021 Heater Level (Day)', choices=TEMP_SENSOR__SI7021_HEATER_LEVEL_choices, validators=[TEMP_SENSOR__SI7021_HEATER_LEVEL_validator])
    TEMP_SENSOR__HTU31D_HEATER_NIGHT = BooleanField('HTU31D Heater (Night)')
    TEMP_SENSOR__HTU31D_HEATER_DAY   = BooleanField('HTU31D Heater (Day)')
    TEMP_SENSOR__HDC302X_HEATER_NIGHT = SelectField('HDC302x Heater (Night)', choices=TEMP_SENSOR__HDC302X_HEATER_choices, validators=[TEMP_SENSOR__HDC302X_HEATER_validator])
    TEMP_SENSOR__HDC302X_HEATER_DAY   = SelectField('HDC302x Heater (Day)', choices=TEMP_SENSOR__HDC302X_HEATER_choices, validators=[TEMP_SENSOR__HDC302X_HEATER_validator])
    TEMP_SENSOR__TSL2561_GAIN_NIGHT  = SelectField('TSL2561 Gain (Night)', choices=TEMP_SENSOR__TSL2561_GAIN_choices, validators=[TEMP_SENSOR__TSL2561_GAIN_validator])
    TEMP_SENSOR__TSL2561_GAIN_DAY    = SelectField('TSL2561 Gain (Day)', choices=TEMP_SENSOR__TSL2561_GAIN_choices, validators=[TEMP_SENSOR__TSL2561_GAIN_validator])
    TEMP_SENSOR__TSL2561_INT_NIGHT   = SelectField('TSL2561 Integration (Night)', choices=TEMP_SENSOR__TSL2561_INT_choices, validators=[TEMP_SENSOR__TSL2561_INT_validator])
    TEMP_SENSOR__TSL2561_INT_DAY     = SelectField('TSL2561 Integration (Day)', choices=TEMP_SENSOR__TSL2561_INT_choices, validators=[TEMP_SENSOR__TSL2561_INT_validator])
    TEMP_SENSOR__TSL2591_GAIN_NIGHT  = SelectField('TSL2591 Gain (Night)', choices=TEMP_SENSOR__TSL2591_GAIN_choices, validators=[TEMP_SENSOR__TSL2591_GAIN_validator])
    TEMP_SENSOR__TSL2591_GAIN_DAY    = SelectField('TSL2591 Gain (Day)', choices=TEMP_SENSOR__TSL2591_GAIN_choices, validators=[TEMP_SENSOR__TSL2591_GAIN_validator])
    TEMP_SENSOR__TSL2591_INT_NIGHT   = SelectField('TSL2591 Integration (Night)', choices=TEMP_SENSOR__TSL2591_INT_choices, validators=[TEMP_SENSOR__TSL2591_INT_validator])
    TEMP_SENSOR__TSL2591_INT_DAY     = SelectField('TSL2591 Integration (Day)', choices=TEMP_SENSOR__TSL2591_INT_choices, validators=[TEMP_SENSOR__TSL2591_INT_validator])
    TEMP_SENSOR__VEML7700_GAIN_NIGHT = SelectField('VEML7700 Gain (Night)', choices=TEMP_SENSOR__VEML7700_GAIN_choices, validators=[TEMP_SENSOR__VEML7700_GAIN_validator])
    TEMP_SENSOR__VEML7700_GAIN_DAY   = SelectField('VEML7700 Gain (Day)', choices=TEMP_SENSOR__VEML7700_GAIN_choices, validators=[TEMP_SENSOR__VEML7700_GAIN_validator])
    TEMP_SENSOR__VEML7700_INT_NIGHT  = SelectField('VEML7700 Integration (Night)', choices=TEMP_SENSOR__VEML7700_INT_choices, validators=[TEMP_SENSOR__VEML7700_INT_validator])
    TEMP_SENSOR__VEML7700_INT_DAY    = SelectField('VEML7700 Integration (Day)', choices=TEMP_SENSOR__VEML7700_INT_choices, validators=[TEMP_SENSOR__VEML7700_INT_validator])
    TEMP_SENSOR__SI1145_VIS_GAIN_NIGHT = SelectField('SI1145 Visible Gain (Night)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_VIS_GAIN_DAY   = SelectField('SI1145 Visible Gain (Day)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_IR_GAIN_NIGHT  = SelectField('SI1145 IR Gain (Night)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_IR_GAIN_DAY    = SelectField('SI1145 IR Gain (Day)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__LTR390_GAIN_NIGHT     = SelectField('LTR390 Gain (Night)', choices=TEMP_SENSOR__LTR390_GAIN_choices, validators=[TEMP_SENSOR__LTR390_GAIN_validator])
    TEMP_SENSOR__LTR390_GAIN_DAY       = SelectField('LTR390 Gain (Day)', choices=TEMP_SENSOR__LTR390_GAIN_choices, validators=[TEMP_SENSOR__LTR390_GAIN_validator])
    CHARTS__CUSTOM_SLOT_1            = SelectField('Extra Chart Slot 1', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_2            = SelectField('Extra Chart Slot 2', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_3            = SelectField('Extra Chart Slot 3', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_4            = SelectField('Extra Chart Slot 4', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_5            = SelectField('Extra Chart Slot 5', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_6            = SelectField('Extra Chart Slot 6', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_7            = SelectField('Extra Chart Slot 7', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_8            = SelectField('Extra Chart Slot 8', choices=[], validators=[SENSOR_SLOT_validator])
    CHARTS__CUSTOM_SLOT_9            = SelectField('Extra Chart Slot 9', choices=[], validators=[SENSOR_SLOT_validator])
    ADSB__ENABLE                     = BooleanField('Enable ADS-B Tracking')
    ADSB__DUMP1090_URL               = StringField('Dump1090 URL', validators=[ADSB__DUMP1090_URL_validator])
    ADSB__USERNAME                   = StringField('Username', validators=[ADSB__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    ADSB__PASSWORD                   = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[ADSB__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    ADSB__CERT_BYPASS                = BooleanField('Disable Certificate Validation')
    ADSB__ALT_DEG_MIN                = FloatField('Minimum Altitude (Degrees)', validators=[DataRequired(), ADSB__ALT_DEG_MIN_validator])
    ADSB__LABEL_ENABLE               = BooleanField('Enable Image Label')
    ADSB__LABEL_LIMIT                = IntegerField('Label Limit', validators=[DataRequired(), ADSB__LABEL_LIMIT_validator])
    ADSB__AIRCRAFT_LABEL_TEMPLATE    = StringField('Aircraft Label Template', validators=[DataRequired(), ADSB__AIRCRAFT_LABEL_TEMPLATE_validator])
    ADSB__IMAGE_LABEL_TEMPLATE_PREFIX   = TextAreaField('Image Template Prefix', validators=[DataRequired(), ADSB__IMAGE_LABEL_TEMPLATE_PREFIX_validator])
    SATELLITE_TRACK__ENABLE          = BooleanField('Enable Satellite Tracking')
    SATELLITE_TRACK__DAYTIME_TRACK   = BooleanField('Daytime Tracking')
    SATELLITE_TRACK__ALT_DEG_MIN     = FloatField('Minimum Altitude (Degrees)', validators=[DataRequired(), SATELLITE_TRACK__ALT_DEG_MIN_validator])
    SATELLITE_TRACK__LABEL_ENABLE    = BooleanField('Enable Image Label')
    SATELLITE_TRACK__LABEL_LIMIT     = IntegerField('Label Limit', validators=[DataRequired(), SATELLITE_TRACK__LABEL_LIMIT_validator])
    SATELLITE_TRACK__SAT_LABEL_TEMPLATE = StringField('Satellite Label Template', validators=[DataRequired(), SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator])
    SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX = TextAreaField('Image Template Prefix', validators=[DataRequired(), SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX_validator])
    INDI_CONFIG_DEFAULTS             = TextAreaField('INDI Camera Config (Default)', validators=[DataRequired(), INDI_CONFIG_DEFAULTS_validator])
    INDI_CONFIG_DAY                  = TextAreaField('INDI Camera Config (Day)', validators=[DataRequired(), INDI_CONFIG_DAY_validator])

    RELOAD_ON_SAVE                   = BooleanField('Reload on Save')
    CONFIG_NOTE                      = StringField('Config Note')

    ADMIN_NETWORKS_FLASK             = TextAreaField('Admin Networks', render_kw={'readonly' : True, 'disabled' : 'disabled'})


    def __init__(self, *args, **kwargs):
        super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)

        from ..devices import sensors as indi_allsky_sensors

        data = kwargs['data']


        temp_sensor__a_classname = str(data['TEMP_SENSOR__A_CLASSNAME'])
        temp_sensor__a_label = str(data['TEMP_SENSOR__A_LABEL'])
        temp_sensor__a_user_var_slot = str(data['TEMP_SENSOR__A_USER_VAR_SLOT'])
        temp_sensor__b_classname = str(data['TEMP_SENSOR__B_CLASSNAME'])
        temp_sensor__b_label = str(data['TEMP_SENSOR__B_LABEL'])
        temp_sensor__b_user_var_slot = str(data['TEMP_SENSOR__B_USER_VAR_SLOT'])
        temp_sensor__c_classname = str(data['TEMP_SENSOR__C_CLASSNAME'])
        temp_sensor__c_label = str(data['TEMP_SENSOR__C_LABEL'])
        temp_sensor__c_user_var_slot = str(data['TEMP_SENSOR__C_USER_VAR_SLOT'])


        if temp_sensor__a_classname:
            try:
                temp_sensor__a_class = getattr(indi_allsky_sensors, temp_sensor__a_classname)
                slot_a_index = constants.SENSOR_INDEX_MAP[temp_sensor__a_user_var_slot]

                for x in range(temp_sensor__a_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOT_choices['User Sensors'][slot_a_index + x][1] = '({0:d}) {1:s} - {2:s} - {3:s}'.format(
                            slot_a_index + x,
                            temp_sensor__a_class.METADATA['name'],
                            temp_sensor__a_label,
                            temp_sensor__a_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__a_classname)


        if temp_sensor__b_classname:
            try:
                temp_sensor__b_class = getattr(indi_allsky_sensors, temp_sensor__b_classname)
                slot_b_index = constants.SENSOR_INDEX_MAP[temp_sensor__b_user_var_slot]

                for x in range(temp_sensor__b_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOT_choices['User Sensors'][slot_b_index + x][1] = '({0:d}) {1:s} - {2:s} - {3:s}'.format(
                            slot_b_index + x,
                            temp_sensor__b_class.METADATA['name'],
                            temp_sensor__b_label,
                            temp_sensor__b_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__b_classname)


        if temp_sensor__c_classname:
            try:
                temp_sensor__c_class = getattr(indi_allsky_sensors, temp_sensor__c_classname)
                slot_c_index = constants.SENSOR_INDEX_MAP[temp_sensor__c_user_var_slot]

                for x in range(temp_sensor__c_class.METADATA['count']):
                    try:
                        self.SENSOR_SLOT_choices['User Sensors'][slot_c_index + x][1] = '({0:d}) {1:s} - {2:s} - {3:s}'.format(
                            slot_c_index + x,
                            temp_sensor__c_class.METADATA['name'],
                            temp_sensor__c_label,
                            temp_sensor__c_class.METADATA['labels'][x],
                        )
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__c_classname)


        # Set system temp names
        temp_info = psutil.sensors_temperatures()

        temp_label_list = list()
        for t_key in sorted(temp_info):  # always return the keys in the same order
            for i, t in enumerate(temp_info[t_key]):
                # these names will match the mqtt topics
                if not t.label:
                    # use index for label name
                    label = str(i)
                else:
                    label = t.label

                topic = '{0:s}/{1:s}'.format(t_key, label)
                temp_label_list.append(topic)


        for x, label in enumerate(temp_label_list[:20]):  # limit to 20
            self.SENSOR_SLOT_choices['System Sensors'][x + 10][1] = '({0:d}) {1:s}'.format(x + 10, label)


        ### Update the choices
        self.DEW_HEATER__TEMP_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices
        self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices
        self.FAN__TEMP_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_1.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_2.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_3.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_4.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_5.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_6.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_7.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_8.choices = self.SENSOR_SLOT_choices
        self.CHARTS__CUSTOM_SLOT_9.choices = self.SENSOR_SLOT_choices


    def validate(self):
        result = super(IndiAllskyConfigForm, self).validate()

        # exposure checking
        if self.CCD_EXPOSURE_DEF.data > self.CCD_EXPOSURE_MAX.data:
            self.CCD_EXPOSURE_DEF.errors.append('Default exposure cannot be greater than max exposure')
            self.CCD_EXPOSURE_MAX.errors.append('Max exposure is less than default exposure')
            result = False

        if self.CCD_EXPOSURE_MIN.data > self.CCD_EXPOSURE_MAX.data:
            self.CCD_EXPOSURE_DEF.errors.append('Minimum exposure cannot be greater than max exposure')
            self.CCD_EXPOSURE_MAX.errors.append('Max exposure is less than minimum exposure')
            result = False


        # require custom font to be defined
        if self.TEXT_PROPERTIES__PIL_FONT_FILE.data == 'custom':
            if not self.TEXT_PROPERTIES__PIL_FONT_CUSTOM.data:
                self.TEXT_PROPERTIES__PIL_FONT_CUSTOM.errors.append('Please set a custom font')
                result = False


        # check cropping
        mod_image_crop_x = (self.IMAGE_CROP_ROI_X2.data - self.IMAGE_CROP_ROI_X1.data) % 2
        if mod_image_crop_x:
            self.IMAGE_CROP_ROI_X2.errors.append('X coordinates must be divisible by 2')
            result = False

        mod_image_crop_y = (self.IMAGE_CROP_ROI_Y2.data - self.IMAGE_CROP_ROI_Y1.data) % 2
        if mod_image_crop_y:
            self.IMAGE_CROP_ROI_Y2.errors.append('Y coordinates must be divisible by 2')
            result = False


        # border
        if (self.IMAGE_BORDER__TOP.data + self.IMAGE_BORDER__BOTTOM.data) % 2:
            self.IMAGE_BORDER__TOP.errors.append('Sum of top and bottom border must be divisible by 2')
            self.IMAGE_BORDER__BOTTOM.errors.append('Sum of top and bottom border must be divisible by 2')
            result = False

        if (self.IMAGE_BORDER__LEFT.data + self.IMAGE_BORDER__RIGHT.data) % 2:
            self.IMAGE_BORDER__LEFT.errors.append('Sum of left and right border must be divisible by 2')
            self.IMAGE_BORDER__RIGHT.errors.append('Sum of left and right border must be divisible by 2')
            result = False


        # focuser
        if self.FOCUSER__CLASSNAME.data:
            if self.FOCUSER__CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.FOCUSER__GPIO_PIN_1.data:
                        try:
                            getattr(board, self.FOCUSER__GPIO_PIN_1.data)
                        except AttributeError:
                            self.FOCUSER__GPIO_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FOCUSER__GPIO_PIN_1.data))
                            result = False
                    else:
                        self.FOCUSER__GPIO_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.FOCUSER__GPIO_PIN_2.data:
                        try:
                            getattr(board, self.FOCUSER__GPIO_PIN_2.data)
                        except AttributeError:
                            self.FOCUSER__GPIO_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.FOCUSER__GPIO_PIN_2.data))
                            result = False
                    else:
                        self.FOCUSER__GPIO_PIN_2.errors.append('PIN must be defined')
                        result = False

                    if self.FOCUSER__GPIO_PIN_3.data:
                        try:
                            getattr(board, self.FOCUSER__GPIO_PIN_3.data)
                        except AttributeError:
                            self.FOCUSER__GPIO_PIN_3.errors.append('PIN {0:s} not valid for your system'.format(self.FOCUSER__GPIO_PIN_3.data))
                            result = False
                    else:
                        self.FOCUSER__GPIO_PIN_3.errors.append('PIN must be defined')
                        result = False

                    if self.FOCUSER__GPIO_PIN_4.data:
                        try:
                            getattr(board, self.FOCUSER__GPIO_PIN_4.data)
                        except AttributeError:
                            self.FOCUSER__GPIO_PIN_4.errors.append('PIN {0:s} not valid for your system'.format(self.FOCUSER__GPIO_PIN_4.data))
                            result = False
                    else:
                        self.FOCUSER__GPIO_PIN_4.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.FOCUSER__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.FOCUSER__GPIO_PIN_1.errors.append('GPIO permissions need to be fixed')
                    self.FOCUSER__GPIO_PIN_2.errors.append('GPIO permissions need to be fixed')
                    self.FOCUSER__GPIO_PIN_3.errors.append('GPIO permissions need to be fixed')
                    self.FOCUSER__GPIO_PIN_4.errors.append('GPIO permissions need to be fixed')
                    result = False


        # dew heater
        if self.DEW_HEATER__CLASSNAME.data:
            if self.DEW_HEATER__CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.DEW_HEATER__PIN_1.data:
                        try:
                            getattr(board, self.DEW_HEATER__PIN_1.data)
                        except AttributeError:
                            self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                            result = False
                    else:
                        self.DEW_HEATER__PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.DEW_HEATER__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.DEW_HEATER__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


        if self.DEW_HEATER__THOLD_DIFF_HIGH.data >= self.DEW_HEATER__THOLD_DIFF_MED.data:
            self.DEW_HEATER__THOLD_DIFF_HIGH.errors.append('HIGH must be less than MEDIUM')
            self.DEW_HEATER__THOLD_DIFF_MED.errors.append('MEDIUM must be greater than HIGH')
            result = False

        if self.DEW_HEATER__THOLD_DIFF_MED.data >= self.DEW_HEATER__THOLD_DIFF_LOW.data:
            self.DEW_HEATER__THOLD_DIFF_MED.errors.append('MEDIUM must be less than LOW')
            self.DEW_HEATER__THOLD_DIFF_LOW.errors.append('LOW must be greater than MEDIUM')
            result = False


        # fan
        if self.FAN__CLASSNAME.data:
            if self.FAN__CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.FAN__PIN_1.data:
                        try:
                            getattr(board, self.FAN__PIN_1.data)
                        except AttributeError:
                            self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                            result = False
                    else:
                        self.FAN__PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.FAN__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.FAN__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


        if self.FAN__THOLD_DIFF_HIGH.data <= self.FAN__THOLD_DIFF_MED.data:
            self.FAN__THOLD_DIFF_HIGH.errors.append('HIGH must be greater than MEDIUM')
            self.FAN__THOLD_DIFF_MED.errors.append('MEDIUM must be less than HIGH')
            result = False

        if self.DEW_HEATER__THOLD_DIFF_MED.data <= self.FAN__THOLD_DIFF_LOW.data:
            self.FAN__THOLD_DIFF_MED.errors.append('MEDIUM must be greater than LOW')
            self.FAN__THOLD_DIFF_LOW.errors.append('LOW must be less than MEDIUM')
            result = False


        # generic gpio
        if self.GENERIC_GPIO__A_CLASSNAME.data:
            if self.GENERIC_GPIO__A_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.GENERIC_GPIO__A_PIN_1.data:
                        try:
                            getattr(board, self.GENERIC_GPIO__A_PIN_1.data)
                        except AttributeError:
                            self.GENERIC_GPIO__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.GENERIC_GPIO__A_PIN_1.data))
                            result = False
                    else:
                        self.GENERIC_GPIO__A_PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.GENERIC_GPIO__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.GENERIC_GPIO__A_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


        # sensor A
        if self.TEMP_SENSOR__A_CLASSNAME.data:
            if self.TEMP_SENSOR__A_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__A_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__A_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__A_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__A_PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__A_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

            elif self.TEMP_SENSOR__A_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__A_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__A_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__A_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__A_PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False


        # sensor B
        if self.TEMP_SENSOR__B_CLASSNAME.data:
            if self.TEMP_SENSOR__B_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__B_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__B_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__B_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__B_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__B_PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__B_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

            elif self.TEMP_SENSOR__B_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__B_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__B_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__B_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__B_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__B_PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False


        # sensor C
        if self.TEMP_SENSOR__C_CLASSNAME.data:
            if self.TEMP_SENSOR__C_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__C_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__C_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__C_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__C_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__C_PIN_1.errors.append('PIN must be defined')
                        result = False

                except NotImplementedError:
                    self.FOCUSER__CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__C_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

            elif self.TEMP_SENSOR__C_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__C_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__C_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__C_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__C_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__C_PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False


        ### ensure sensor slots are unique
        ### (disabled, let them be duplicate)
        #custom_charts = (
        #    self.CHARTS__CUSTOM_SLOT_1,
        #    self.CHARTS__CUSTOM_SLOT_2,
        #    self.CHARTS__CUSTOM_SLOT_3,
        #    self.CHARTS__CUSTOM_SLOT_4,
        #    self.CHARTS__CUSTOM_SLOT_5,
        #    self.CHARTS__CUSTOM_SLOT_6,
        #    self.CHARTS__CUSTOM_SLOT_7,
        #    self.CHARTS__CUSTOM_SLOT_8,
        #    self.CHARTS__CUSTOM_SLOT_9,
        #)

        #for chart1, chart2 in itertools.combinations(custom_charts, 2):
        #    if chart1.data == chart2.data:
        #        chart1.errors.append('Duplicate chart defined')
        #        chart2.errors.append('Duplicate chart defined')
        #        result = False



        check_sensor_slots = list()
        if self.TEMP_SENSOR__A_CLASSNAME.data:
            check_sensor_slots.append(self.TEMP_SENSOR__A_USER_VAR_SLOT)

        if self.TEMP_SENSOR__B_CLASSNAME.data:
            check_sensor_slots.append(self.TEMP_SENSOR__B_USER_VAR_SLOT)

        if self.TEMP_SENSOR__C_CLASSNAME.data:
            check_sensor_slots.append(self.TEMP_SENSOR__C_USER_VAR_SLOT)


        for slot1, slot2 in itertools.combinations(check_sensor_slots, 2):
            if slot1.data == slot2.data:
                slot1.errors.append('Duplicate slot defined')
                slot2.errors.append('Duplicate slot defined')
                result = False


        if self.DEW_HEATER__THOLD_ENABLE.data:
            if self.DEW_HEATER__TEMP_USER_VAR_SLOT.data == self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.data:
                self.DEW_HEATER__TEMP_USER_VAR_SLOT.errors.append('Sensor same as dew point')
                self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.errors.append('Sensor same as temperature')
                result = False


        ### these never seem to be hit
        #from ..devices import sensors as indi_allsky_sensors
        #temp_sensor__a_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__A_CLASSNAME.data)
        #sensor_a_count = temp_sensor__a_class.METADATA['count']
        #slot_a_index = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__A_USER_VAR_SLOT.data]

        #if sensor_a_count + slot_a_index > 30:
        #    self.TEMP_SENSOR__A_USER_VAR_SLOT.errors.append('Not enough sensor slots')
        #    result = False


        return result


class IndiAllskyImageViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    IMG_SELECT           = SelectField('Image', choices=[], validators=[])
    FILTER_DETECTIONS    = BooleanField('Detections')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewer, self).__init__(*args, **kwargs)

        self.detections_count = kwargs.get('detections_count', 0)
        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                )
        )


        if not self.local:
            # Do not serve local assets
            days_query = days_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        days_query = days_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                )
        )


        if not self.local:
            # Do not serve local assets
            hours_query = hours_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        hours_query = hours_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                    IndiAllSkyDbImageTable.createDate_hour == hour,
                )
        )


        if not self.local:
            # Do not serve local assets
            images_query = images_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        images_query = images_query\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        images_data = list()
        for img in images_query:
            try:
                url = img.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            if img.detections:
                entry_str = '{0:s} [*]'.format(img.createDate.strftime('%H:%M:%S'))
            else:
                entry_str = img.createDate.strftime('%H:%M:%S')

            image_dict = dict()
            image_dict['id'] = img.id
            image_dict['url'] = str(url)
            image_dict['date'] = entry_str
            image_dict['ts'] = int(img.createDate.timestamp())
            image_dict['width'] = img.width
            image_dict['height'] = img.height
            image_dict['exclude'] = img.exclude


            # look for fits
            try:
                fits_image = db.session.query(
                    IndiAllSkyDbFitsImageTable,
                )\
                    .filter(IndiAllSkyDbFitsImageTable.createDate == img.createDate)\
                    .one()

                image_dict['fits'] = str(fits_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['fits_id'] = fits_image.id
            except NoResultFound:
                image_dict['fits'] = None
                image_dict['fits_id'] = None


            # look for raw exports
            try:
                raw_image = db.session.query(
                    IndiAllSkyDbRawImageTable,
                )\
                    .filter(IndiAllSkyDbRawImageTable.createDate == img.createDate)\
                    .one()

                image_dict['raw'] = str(raw_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['raw_id'] = raw_image.id
            except NoResultFound:
                image_dict['raw'] = None
                image_dict['raw_id'] = None
            except ValueError:
                # this can happen when RAW files are exported outside of the document root
                image_dict['raw'] = None
                image_dict['raw_id'] = None


            # look for panorama
            try:
                panorama_image = db.session.query(
                    IndiAllSkyDbPanoramaImageTable,
                )\
                    .filter(IndiAllSkyDbPanoramaImageTable.createDate == img.createDate)\
                    .one()

                image_dict['panorama'] = str(panorama_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['panorama_id'] = panorama_image.id
            except NoResultFound:
                image_dict['panorama'] = None
                image_dict['panorama_id'] = None


            images_data.append(image_dict)


        return images_data


class IndiAllskyImageViewerPreload(IndiAllskyImageViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewerPreload, self).__init__(*args, **kwargs)

        last_image = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()

        if not last_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)
            self.IMG_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)
        self.IMG_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyFitsImageViewer(FlaskForm):
    model = IndiAllSkyDbFitsImageTable

    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    IMG_SELECT           = SelectField('Image', choices=[], validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyFitsImageViewer, self).__init__(*args, **kwargs)

        self.camera_id = kwargs.get('camera_id')


    def getYears(self):
        years_query = db.session.query(
            self.model.createDate_year,
        )\
            .join(self.model.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)


        years_query = years_query\
            .distinct()\
            .order_by(self.model.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        #app.logger.info('Years: %s', year_choices)

        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
        )\
            .join(self.model.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    self.model.createDate_year == year,
                )
        )


        months_query = months_query\
            .distinct()\
            .order_by(self.model.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
            self.model.createDate_day,
        )\
            .join(self.model.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                )
        )


        days_query = days_query\
            .distinct()\
            .order_by(self.model.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
            self.model.createDate_day,
            self.model.createDate_hour,
        )\
            .join(self.model.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                    self.model.createDate_day == day,
                )
        )


        hours_query = hours_query\
            .distinct()\
            .order_by(self.model.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            self.model,
        )\
            .join(self.model.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                    self.model.createDate_day == day,
                    self.model.createDate_hour == hour,
                )
        )


        images_query = images_query\
            .order_by(self.model.createDate.desc())


        images_data = list()
        for img in images_query:
            url = url_for('indi_allsky.fits2jpeg_view', id=img.id)

            entry_str = img.createDate.strftime('%H:%M:%S')

            fits_url = img.getUrl(local=True)

            image_dict = dict()
            image_dict['id'] = img.id
            image_dict['url'] = str(url)
            image_dict['fits'] = str(fits_url)
            image_dict['date'] = entry_str
            image_dict['ts'] = int(img.createDate.timestamp())
            image_dict['width'] = img.width
            image_dict['height'] = img.height


            images_data.append(image_dict)


        return images_data


class IndiAllskyFitsImageViewerPreload(IndiAllskyFitsImageViewer):

    def __init__(self, *args, **kwargs):
        super(IndiAllskyFitsImageViewerPreload, self).__init__(*args, **kwargs)

        last_fits_image = db.session.query(
            self.model,
        )\
            .join(self.model.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .order_by(self.model.createDate.desc())\
            .first()

        if not last_fits_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)
            self.IMG_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)
        self.IMG_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyGalleryViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    FILTER_DETECTIONS    = BooleanField('Detections')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyGalleryViewer, self).__init__(*args, **kwargs)

        self.detections_count = kwargs.get('detections_count', 0)
        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                )
        )

        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                )
        )


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            days_query = days_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        days_query = days_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                )
        )


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            hours_query = hours_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        hours_query = hours_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            IndiAllSkyDbImageTable,
            IndiAllSkyDbThumbnailTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                    IndiAllSkyDbImageTable.createDate_hour == hour,
                )
        )


        if not self.local:
            # Do not serve local assets
            images_query = images_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        images_query = images_query\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        images_data = list()
        for img, thumb in images_query:
            try:
                image_url = img.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                thumbnail_url = thumb.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            image_dict = dict()
            image_dict['date'] = img.createDate.strftime('%H:%M:%S')
            image_dict['url'] = str(image_url)
            image_dict['width'] = img.width
            image_dict['height'] = img.height
            image_dict['thumbnail_url'] = str(thumbnail_url)
            image_dict['thumbnail_width'] = thumb.width
            image_dict['thumbnail_height'] = thumb.height


            images_data.append(image_dict)


        return images_data


class IndiAllskyGalleryViewerPreload(IndiAllskyGalleryViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyGalleryViewerPreload, self).__init__(*args, **kwargs)

        last_image = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()


        if not last_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyVideoViewer(FlaskForm):
    TIMEOFDAY_SELECT_choices = (
        ('all', 'All'),
        ('day', 'Day'),
        ('night', 'Night'),
    )

    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    TIMEOFDAY_SELECT     = SelectField('Time of Day', choices=TIMEOFDAY_SELECT_choices, validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyVideoViewer, self).__init__(*args, **kwargs)

        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbVideoTable.dayDate_year,
        )\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbVideoTable.dayDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.dayDate_year, str(y.dayDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbVideoTable.dayDate_year,
            IndiAllSkyDbVideoTable.dayDate_month,
        )\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbVideoTable.dayDate_year == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbVideoTable.dayDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.dayDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.dayDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getVideos(self, year, month, timeofday):
        videos_query = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbVideoTable.dayDate_year == year,
                    IndiAllSkyDbVideoTable.dayDate_month == month,
                )
            )


        # add time of day filter
        if timeofday == 'day':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == sa_false())
        elif timeofday == 'night':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == sa_true())
        else:
            pass


        if not self.local:
            # Do not serve local assets
            videos_query = videos_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        # set order
        videos_query = videos_query.order_by(
            IndiAllSkyDbVideoTable.dayDate.desc(),
            IndiAllSkyDbVideoTable.night.desc(),
            IndiAllSkyDbVideoTable.createDate.desc(),  # there should only be one, but just in case
        )


        videos_data = []
        for v in videos_query:
            try:
                url = v.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            if v.data:
                data = v.data
            else:
                data = {}

            entry = {
                'id'                : v.id,
                'url'               : str(url),
                'success'           : v.success,
                'dayDate_long'      : v.dayDate.strftime('%B %d, %Y'),
                'dayDate'           : v.dayDate.strftime('%Y%m%d'),
                'night'             : v.night,
                'max_smoke_rating'  : constants.SMOKE_RATING_MAP_STR[data.get('max_smoke_rating', constants.SMOKE_RATING_NODATA)],
                'max_kpindex'       : data.get('max_kpindex', 0.0),
                'max_ovation_max'   : data.get('max_ovation_max', 0),
                'max_moonphase'     : data.get('max_moonphase', 0),  # might be null
                'max_stars'         : int(data.get('max_stars', 0)),
                'avg_stars'         : int(data.get('avg_stars', 0)),
                'avg_sqm'           : int(data.get('avg_sqm', 0)),
                'youtube_uploaded'  : bool(data.get('youtube_id', False)),
            }
            videos_data.append(entry)

        # cannot query the DB from inside the DB query
        for entry in videos_data:
            dayDate = datetime.strptime(entry['dayDate'], '%Y%m%d').date()

            # Querying the oldest due to a bug where regeneated files are added with the wrong dayDate
            # fix is inbound

            ### Keogram
            keogram_entry_q = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == self.camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == dayDate,
                        IndiAllSkyDbKeogramTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                keogram_entry_q = keogram_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbKeogramTable.remote_url != sa_null(),
                            IndiAllSkyDbKeogramTable.s3_key != sa_null(),
                        )
                    )


            keogram_entry = keogram_entry_q\
                .order_by(IndiAllSkyDbKeogramTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if keogram_entry:
                try:
                    keogram_url = keogram_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    keogram_id = keogram_entry.id
                    keogram_success = keogram_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    keogram_url = None
                    keogram_id = 0
                    keogram_success = False


                if keogram_entry.thumbnail_uuid:
                    keogram_thumbnail_entry = IndiAllSkyDbThumbnailTable.query\
                        .filter(IndiAllSkyDbThumbnailTable.uuid == keogram_entry.thumbnail_uuid)\
                        .first()

                    if keogram_thumbnail_entry:
                        try:
                            keogram_thumbnail_url = keogram_thumbnail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                        except ValueError:
                            keogram_thumbnail_url = None
                    else:
                        keogram_thumbnail_url = None
                else:
                    keogram_thumbnail_url = None
            else:
                keogram_url = None
                keogram_id = -1
                keogram_thumbnail_url = None
                keogram_success = False


            ### Star trail
            startrail_entry_q = IndiAllSkyDbStarTrailsTable.query\
                .join(IndiAllSkyDbStarTrailsTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == self.camera_id,
                        IndiAllSkyDbStarTrailsTable.dayDate == dayDate,
                        IndiAllSkyDbStarTrailsTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                startrail_entry_q = startrail_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbStarTrailsTable.remote_url != sa_null(),
                            IndiAllSkyDbStarTrailsTable.s3_key != sa_null(),
                        )
                    )


            startrail_entry = startrail_entry_q\
                .order_by(IndiAllSkyDbStarTrailsTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if startrail_entry:
                try:
                    startrail_url = startrail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    startrail_id = startrail_entry.id
                    startrail_success = startrail_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    startrail_url = None
                    startrail_id = -1
                    startrail_success = False


                if startrail_entry.thumbnail_uuid:
                    startrail_thumbnail_entry = IndiAllSkyDbThumbnailTable.query\
                        .filter(IndiAllSkyDbThumbnailTable.uuid == startrail_entry.thumbnail_uuid)\
                        .first()

                    if startrail_thumbnail_entry:
                        try:
                            startrail_thumbnail_url = startrail_thumbnail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                        except ValueError:
                            startrail_thumbnail_url = None
                    else:
                        startrail_thumbnail_url = None
                else:
                    startrail_thumbnail_url = None
            else:
                startrail_url = None
                startrail_id = -1
                startrail_thumbnail_url = None
                startrail_success = False


            ### Star trail timelapses
            startrail_video_entry_q = IndiAllSkyDbStarTrailsVideoTable.query\
                .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == self.camera_id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == dayDate,
                        IndiAllSkyDbStarTrailsVideoTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                startrail_video_entry_q = startrail_video_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbStarTrailsVideoTable.remote_url != sa_null(),
                            IndiAllSkyDbStarTrailsVideoTable.s3_key != sa_null(),
                        )
                    )


            startrail_video_entry = startrail_video_entry_q\
                .order_by(IndiAllSkyDbStarTrailsVideoTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if startrail_video_entry:
                if startrail_video_entry.data:
                    st_v_data = startrail_video_entry.data
                else:
                    st_v_data = {}

                try:
                    startrail_video_url = startrail_video_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    startrail_video_id = startrail_video_entry.id
                    startrail_video_youtube = bool(st_v_data.get('youtube_id', False))
                    startrail_video_success = startrail_video_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    startrail_video_url = None
                    startrail_video_id = -1
                    startrail_video_youtube = False
                    startrail_video_success = False
            else:
                startrail_video_url = None
                startrail_video_id = -1
                startrail_video_youtube = False
                startrail_video_success = False


            ### Panorama timelapses
            panorama_video_entry_q = IndiAllSkyDbPanoramaVideoTable.query\
                .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == self.camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == dayDate,
                        IndiAllSkyDbPanoramaVideoTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                panorama_video_entry_q = panorama_video_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbPanoramaVideoTable.remote_url != sa_null(),
                            IndiAllSkyDbPanoramaVideoTable.s3_key != sa_null(),
                        )
                    )


            panorama_video_entry = panorama_video_entry_q\
                .order_by(IndiAllSkyDbPanoramaVideoTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if panorama_video_entry:
                if panorama_video_entry.data:
                    p_v_data = panorama_video_entry.data
                else:
                    p_v_data = {}

                try:
                    panorama_video_url = panorama_video_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    panorama_video_id = panorama_video_entry.id
                    panorama_video_youtube = bool(p_v_data.get('youtube_id', False))
                    panorama_video_success = panorama_video_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    panorama_video_url = None
                    panorama_video_id = -1
                    panorama_video_youtube = False
                    panorama_video_success = False
            else:
                panorama_video_url = None
                panorama_video_id = -1
                panorama_video_youtube = False
                panorama_video_success = False


            entry['keogram']    = str(keogram_url)
            entry['keogram_id'] = keogram_id
            entry['keogram_thumbnail']  = str(keogram_thumbnail_url)
            entry['keogram_success']  = keogram_success
            entry['startrail']  = str(startrail_url)
            entry['startrail_thumbnail']  = str(startrail_thumbnail_url)
            entry['startrail_id']  = startrail_id
            entry['startrail_success']  = startrail_success
            entry['startrail_timelapse']  = str(startrail_video_url)
            entry['startrail_timelapse_id']  = startrail_video_id
            entry['startrail_timelapse_youtube_uploaded']  = startrail_video_youtube
            entry['startrail_timelapse_success']  = startrail_video_success
            entry['panorama_timelapse']  = str(panorama_video_url)
            entry['panorama_timelapse_id']  = panorama_video_id
            entry['panorama_timelapse_youtube_uploaded']  = panorama_video_youtube
            entry['panorama_timelapse_success']  = panorama_video_success


        return videos_data



class IndiAllskyVideoViewerPreload(IndiAllskyVideoViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyVideoViewerPreload, self).__init__(*args, **kwargs)

        last_video = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .order_by(IndiAllSkyDbVideoTable.dayDate.desc())\
            .first()

        if not last_video:
            app.logger.warning('No timelapses found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyMiniVideoViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyMiniVideoViewer, self).__init__(*args, **kwargs)

        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbMiniVideoTable.dayDate_year,
        )\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbMiniVideoTable.dayDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.dayDate_year, str(y.dayDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbMiniVideoTable.dayDate_year,
            IndiAllSkyDbMiniVideoTable.dayDate_month,
        )\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbMiniVideoTable.dayDate_year == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbMiniVideoTable.dayDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.dayDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.dayDate_month, month_name)
            month_choices.append(entry)


        return month_choices



    def getVideos(self, year, month):
        videos_query = db.session.query(
            IndiAllSkyDbMiniVideoTable,
            IndiAllSkyDbThumbnailTable,
        )\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbMiniVideoTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbMiniVideoTable.dayDate_year == year,
                    IndiAllSkyDbMiniVideoTable.dayDate_month == month,
                )
        )


        if not self.local:
            # Do not serve local assets
            videos_query = videos_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        # set order
        videos_query = videos_query.order_by(
            IndiAllSkyDbMiniVideoTable.dayDate.desc(),
            IndiAllSkyDbMiniVideoTable.night.desc(),
        )


        videos_data = []
        for v, t in videos_query:
            try:
                url = v.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            try:
                thumbnail_url = t.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            if v.data:
                data = v.data
            else:
                data = {}

            entry = {
                'id'                : v.id,
                'url'               : str(url),
                'success'           : v.success,
                'thumbnail_url'     : str(thumbnail_url),
                'dayDate_long'      : v.dayDate.strftime('%B %d, %Y'),
                'dayDate'           : v.dayDate.strftime('%Y%m%d'),
                'night'             : v.night,
                'note'              : v.note,
                'max_smoke_rating'  : constants.SMOKE_RATING_MAP_STR[data.get('max_smoke_rating', constants.SMOKE_RATING_NODATA)],
                'max_kpindex'       : data.get('max_kpindex', 0.0),
                'max_ovation_max'   : data.get('max_ovation_max', 0),
                'max_moonphase'     : data.get('max_moonphase', 0),  # might be null
                'max_stars'         : int(data.get('max_stars', 0)),
                'avg_stars'         : int(data.get('avg_stars', 0)),
                'avg_sqm'           : int(data.get('avg_sqm', 0)),
                'youtube_uploaded'  : bool(data.get('youtube_id', False)),
            }
            videos_data.append(entry)


        return videos_data


class IndiAllskyMiniVideoViewerPreload(IndiAllskyMiniVideoViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyMiniVideoViewerPreload, self).__init__(*args, **kwargs)

        last_video = IndiAllSkyDbMiniVideoTable.query\
            .join(IndiAllSkyDbMiniVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .order_by(IndiAllSkyDbMiniVideoTable.dayDate.desc())\
            .first()

        if not last_video:
            app.logger.warning('No timelapses found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


#def SERVICE_HIDDEN_validator(form, field):
#    services = (
#        'indiserver.service',
#        'indi-allsky.service',
#        'gunicorn-indi-allsky.service',
#    )
#
#    if field.data not in services:
#        raise ValidationError('Invalid service')



#def COMMAND_HIDDEN_validator(form, field):
#    commands = (
#        'restart',
#        'stop',
#        'start',
#        'hup',
#    )
#
#    if field.data not in commands:
#        raise ValidationError('Invalid command')



class IndiAllskyTimelapseGeneratorForm(FlaskForm):
    ACTION_SELECT_choices = (
        ('none', '(Please select an action)'),
        ('generate_video_k_st', 'Generate All'),
        ('generate_video', 'Generate Timelapse Only'),
        ('generate_k_st', 'Generate Keogram/Star Trails'),
        ('generate_panorama_video', 'Generate Panorama Timelapse'),
        ('delete_video_k_st_p', 'Delete Timelapse/Keogram/Star Trails/Panorama'),
        ('delete_video', 'Delete Timelapse Only'),
        ('delete_k_st', 'Delete Keogram/Star Trails'),
        ('delete_panorama_video', 'Delete Panorama Timelapse'),
        ('upload_endofnight', 'Upload End-of-Night Data [today only]'),
        ('delete_images', 'Delete Images for date *DANGER*'),
    )

    CAMERA_ID          = HiddenField('Camera ID', validators=[DataRequired()])
    ACTION_SELECT      = SelectField('Action', choices=ACTION_SELECT_choices, validators=[DataRequired()])
    DAY_SELECT         = SelectField('Day', choices=[], validators=[DataRequired()])
    CONFIRM1           = BooleanField('Confirm')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyTimelapseGeneratorForm, self).__init__(*args, **kwargs)

        self.camera_id = kwargs['camera_id']

        dates_start = time.time()

        self.DAY_SELECT.choices = self.getDistinctDays(self.camera_id)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


    def getDistinctDays(self, camera_id):
        dayDate_day = func.distinct(IndiAllSkyDbImageTable.dayDate).label('day')

        days_query = db.session.query(
            dayDate_day
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbImageTable.dayDate.desc())


        day_list = list()
        for entry in days_query:
            # cannot query from inside a query
            if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
                day_list.append(entry.day)
            else:
                # assume sqlite
                day_list.append(datetime.strptime(entry.day, '%Y-%m-%d').date())


        day_choices = list()
        for day_date in day_list:
            day_str = day_date.strftime('%Y-%m-%d')

            day_night_str = '{0:s} Night'.format(day_str)
            day_day_str = '{0:s} Day'.format(day_str)


            # videos
            video_entry_night = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if video_entry_night:
                if not video_entry_night.success:
                    day_night_str = '{0:s} [!T]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [T]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            video_entry_day = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == sa_false(),
                    )
                )\
                .first()

            if video_entry_day:
                if not video_entry_day.success:
                    day_day_str = '{0:s} [!T]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [T]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # keogram
            keogram_entry_night = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == sa_true(),
                    )
                )\
                .first()

            if keogram_entry_night:
                if not keogram_entry_night.success:
                    day_night_str = '{0:s} [!K]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [K]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            keogram_entry_day = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == sa_false(),
                    )
                )\
                .first()

            if keogram_entry_day:
                if not keogram_entry_day.success:
                    day_day_str = '{0:s} [!K]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [K]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # star trail
            startrail_entry_night = IndiAllSkyDbStarTrailsTable.query\
                .join(IndiAllSkyDbStarTrailsTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbStarTrailsTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsTable.night == sa_true(),
                    )
                )\
                .first()

            if startrail_entry_night:
                if not startrail_entry_night.success:
                    day_night_str = '{0:s} [!S]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [S]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            # star trail video
            startrail_video_entry_night = IndiAllSkyDbStarTrailsVideoTable.query\
                .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if startrail_video_entry_night:
                if not startrail_video_entry_night.success:
                    day_night_str = '{0:s} [!ST]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [ST]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            # panorama video
            panorama_video_entry_night = IndiAllSkyDbPanoramaVideoTable.query\
                .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if panorama_video_entry_night:
                if not panorama_video_entry_night.success:
                    day_night_str = '{0:s} [!P]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [P]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            panorama_video_entry_day = IndiAllSkyDbPanoramaVideoTable.query\
                .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaVideoTable.night == sa_false(),
                    )
                )\
                .first()

            if panorama_video_entry_day:
                if not panorama_video_entry_day.success:
                    day_day_str = '{0:s} [!P]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [P]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # images
            images_night = IndiAllSkyDbImageTable.query\
                .join(IndiAllSkyDbImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbImageTable.dayDate == day_date,
                        IndiAllSkyDbImageTable.night == sa_true(),
                    )
                )

            panorama_night = IndiAllSkyDbPanoramaImageTable.query\
                .join(IndiAllSkyDbPanoramaImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaImageTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaImageTable.night == sa_true(),
                    )
                )


            day_night_str = '{0:s} - {1:d}/{2:d} images'.format(day_night_str, images_night.count(), panorama_night.count())


            images_day = IndiAllSkyDbImageTable.query\
                .join(IndiAllSkyDbImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbImageTable.dayDate == day_date,
                        IndiAllSkyDbImageTable.night == sa_false(),
                    )
                )

            panorama_day = IndiAllSkyDbPanoramaImageTable.query\
                .join(IndiAllSkyDbPanoramaImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaImageTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaImageTable.night == sa_false(),
                    )
                )

            day_day_str = '{0:s} - {1:d}/{2:d} images'.format(day_day_str, images_day.count(), panorama_day.count())


            entry_night = ('{0:s}_night'.format(day_str), day_night_str)
            day_choices.append(entry_night)

            entry_day = ('{0:s}_day'.format(day_str), day_day_str)
            day_choices.append(entry_day)

        return day_choices



class IndiAllskySystemInfoForm(FlaskForm):
    # fake form to send commands to web application

    CAMERA_ID           = HiddenField('Camera ID', validators=[DataRequired()])
    SERVICE_HIDDEN      = HiddenField('service_hidden', validators=[DataRequired()])
    COMMAND_HIDDEN      = HiddenField('command_hidden', validators=[DataRequired()])



class IndiAllskyLoopHistoryForm(FlaskForm):
    HISTORY_SELECT_choices = (
        ('900', '15 Minutes'),
        ('1800', '30 Minutes'),
        ('2700', '45 Minutes'),
        ('3600', '1 Hour'),
        ('7200', '2 Hours'),
        ('10800', '3 Hours'),
        ('14400', '4 Hours'),
    )

    FRAMEDELAY_SELECT_choices = (
        ('20', '50 FPS'),
        ('40', '25 FPS'),
        ('100', '10 FPS'),
        ('200', '5 FPS'),
    )

    HISTORY_SELECT       = SelectField('History', choices=HISTORY_SELECT_choices, default=HISTORY_SELECT_choices[0][0], validators=[])
    FRAMEDELAY_SELECT    = SelectField('Speed', choices=FRAMEDELAY_SELECT_choices, default=FRAMEDELAY_SELECT_choices[2][0], validators=[])
    ROCK_CHECKBOX        = BooleanField('Rock', default=False)


class IndiAllskyChartHistoryForm(FlaskForm):
    HISTORY_SELECT_choices = (
        ('900', '15 Minutes'),
        ('1800', '30 Minutes'),
        ('2700', '45 Minutes'),
        ('3600', '1 Hour'),
        ('7200', '2 Hours'),
        ('10800', '3 Hours'),
        ('14400', '4 Hours'),
        ('21600', '6 Hours'),
        ('43200', '12 Hours'),
        ('86400', '24 Hours'),
    )

    HISTORY_SELECT       = SelectField('History', choices=HISTORY_SELECT_choices, default=HISTORY_SELECT_choices[0][0], validators=[])


class IndiAllskySetDateTimeForm(FlaskForm):

    NEW_DATETIME = DateTimeLocalField('New Datetime', render_kw={'step' : '1'}, format='%Y-%m-%dT%H:%M:%S', validators=[DataRequired()])



class IndiAllskyFocusForm(FlaskForm):
    ZOOM_SELECT_choices = (
        (2, 'Off'),
        (5, 'Low'),
        (10, 'Medium'),
        (20, 'High'),
        (40, 'Extreme'),
        (60, 'Ridiculous'),
        (80, 'Ludicrous'),
        (100, 'Plaid'),
    )
    REFRESH_SELECT_choices = (
        (2, '2s'),
        (3, '3s'),
        (4, '4s'),
        (5, '5s'),
        (10, '10s'),
        (15, '15s'),
    )


    ZOOM_SELECT       = SelectField('Zoom', choices=ZOOM_SELECT_choices, default=ZOOM_SELECT_choices[0][0], validators=[])
    REFRESH_SELECT    = SelectField('Refresh', choices=REFRESH_SELECT_choices, default=REFRESH_SELECT_choices[3][0], validators=[])
    X_OFFSET          = IntegerField('X Offset', default=0)
    Y_OFFSET          = IntegerField('Y Offset', default=0)


class IndiAllskyLogViewerForm(FlaskForm):
    LINES_SELECT_choices = (
        (25, '25'),
        (100, '100'),
        (500, '500'),
        (1000, '1000'),
        (2000, '2000'),
        (5000, '5000'),
    )
    REFRESH_SELECT_choices = (
        (5, '5s'),
        (15, '15s'),
        (30, '30s'),
        (60, '60s'),
    )


    LINES_SELECT      = SelectField('Lines', choices=LINES_SELECT_choices, default=LINES_SELECT_choices[0][0], validators=[])
    REFRESH_SELECT    = SelectField('Refresh', choices=REFRESH_SELECT_choices, default=REFRESH_SELECT_choices[1][0], validators=[])
    FILTER            = StringField('Filter', validators=[])



def LOGIN__USERNAME_validator(form, field):
    username_regex = r'^[a-zA-Z0-9\@\.\-]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


class IndiAllskyLoginForm(FlaskForm):
    USERNAME          = StringField('Username', validators=[DataRequired(), LOGIN__USERNAME_validator])
    PASSWORD          = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[DataRequired(), FILETRANSFER__PASSWORD_validator])
    NEXT              = HiddenField('Next')


class IndiAllskyCameraSelectForm(FlaskForm):
    CAMERA_SELECT     = SelectField('CAMERA', validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyCameraSelectForm, self).__init__(*args, **kwargs)

        self.CAMERA_SELECT.choices = self.getCameras()


    def getCameras(self):
        cameras = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.id.asc())

        camera_list = list()
        for camera in cameras:
            if camera.friendlyName:
                camera_name = camera.friendlyName
            else:
                camera_name = camera.name

            camera_list.append((camera.id, camera_name))

        return camera_list




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
    USERNAME          = StringField('Username', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    NAME              = StringField('Name', validators=[DataRequired(), USER__NAME_validator])
    EMAIL             = StringField('Email', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    ADMIN             = BooleanField('Admin', render_kw={'disabled' : 'disabled'})
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


class IndiAllskyImageExcludeForm(FlaskForm):
    EXCLUDE_IMAGE_ID    = HiddenField('Image ID', validators=[DataRequired()])
    EXCLUDE_EXCLUDE     = BooleanField('Exclude Image From Timelapse', render_kw={'disabled' : 'disabled'})  # enabled in template


    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageExcludeForm, self).__init__(*args, **kwargs)


class IndiAllskyFocusControllerForm(FlaskForm):
    STEP_DEGREES_choices = (
        (6, '6 degrees'),
        (12, '12 Degrees'),
        (24, '24 Degrees'),
        (45, '45 Degrees'),
        (90, '90 Degrees'),
        (180, '180 Degrees'),
    )

    DIRECTION           = StringField('Direction')
    STEP_DEGREES        = SelectField('Degrees', choices=STEP_DEGREES_choices, default=STEP_DEGREES_choices[2][0], validators=[])


class IndiAllskyImageProcessingForm(FlaskForm):
    DISABLE_PROCESSING               = BooleanField('Disable processing')
    CAMERA_ID                        = HiddenField('Camera ID', validators=[DataRequired()])
    FRAME_TYPE                       = HiddenField('FRAME_TYPE', validators=[DataRequired()])
    FITS_ID                          = HiddenField('FITS ID', validators=[DataRequired()])
    LENS_OFFSET_X                    = IntegerField('Lens X Offset', validators=[LENS_OFFSET_validator])
    LENS_OFFSET_Y                    = IntegerField('Lens Y Offset', validators=[LENS_OFFSET_validator])
    IMAGE_CALIBRATE_DARK             = BooleanField('Dark Frame Calibration')
    IMAGE_CALIBRATE_BPM              = BooleanField('Bad Pixel Map Calibration')
    CCD_BIT_DEPTH                    = SelectField('Camera Bit Depth', choices=IndiAllskyConfigForm.CCD_BIT_DEPTH_choices, validators=[CCD_BIT_DEPTH_validator])
    NIGHT_CONTRAST_ENHANCE           = BooleanField('Contrast Enhance')
    CONTRAST_ENHANCE_16BIT           = BooleanField('16-bit Contrast Enhance')
    CLAHE_CLIPLIMIT                  = FloatField('CLAHE Clip Limit', validators=[CLAHE_CLIPLIMIT_validator])
    CLAHE_GRIDSIZE                   = IntegerField('CLAHE Grid Size', validators=[CLAHE_GRIDSIZE_validator])
    IMAGE_STRETCH__CLASSNAME         = SelectField('Stretch Function', choices=IndiAllskyConfigForm.IMAGE_STRETCH__CLASSNAME_choices, validators=[IMAGE_STRETCH__CLASSNAME_validator])
    IMAGE_STRETCH__MODE1_GAMMA       = FloatField('Stretching Gamma', validators=[IMAGE_STRETCH__MODE1_GAMMA_validator])
    IMAGE_STRETCH__MODE1_STDDEVS     = FloatField('Stretching Std Deviations', validators=[DataRequired(), IMAGE_STRETCH__MODE1_STDDEVS_validator])
    IMAGE_STRETCH__MODE2_SHADOWS     = FloatField('MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE2_SHADOWS_validator])
    IMAGE_STRETCH__MODE2_MIDTONES    = FloatField('MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE2_MIDTONES_validator])
    IMAGE_STRETCH__MODE2_HIGHLIGHTS  = FloatField('MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator])
    #IMAGE_STRETCH__SPLIT            = BooleanField('Stretching split screen')
    CFA_PATTERN                      = SelectField('Bayer Pattern', choices=IndiAllskyConfigForm.CFA_PATTERN_choices, validators=[CFA_PATTERN_validator])
    SCNR_ALGORITHM                   = SelectField('SCNR (green reduction)', choices=IndiAllskyConfigForm.SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    WBR_FACTOR                       = FloatField('Red Balance Factor', validators=[WB_FACTOR_validator])
    WBG_FACTOR                       = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator])
    WBB_FACTOR                       = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator])
    AUTO_WB                          = BooleanField('Auto White Balance')
    SATURATION_FACTOR                = FloatField('Saturation Factor', validators=[SATURATION_FACTOR_validator])
    GAMMA_CORRECTION                 = FloatField('Gamma Correction', validators=[GAMMA_CORRECTION_validator])
    IMAGE_ROTATE                     = SelectField('Rotate Image', choices=IndiAllskyConfigForm.IMAGE_ROTATE_choices, validators=[IMAGE_ROTATE_validator])
    IMAGE_ROTATE_ANGLE               = IntegerField('Rotation Angle', validators=[IMAGE_ROTATE_ANGLE_validator])
    IMAGE_FLIP_V                     = BooleanField('Flip Image Vertically')
    IMAGE_FLIP_H                     = BooleanField('Flip Image Horizontally')
    DETECT_MASK                      = StringField('Detection Mask', validators=[DETECT_MASK_validator])
    SQM_ROI_X1                       = IntegerField('SQM ROI x1', validators=[SQM_ROI_validator])
    SQM_ROI_Y1                       = IntegerField('SQM ROI y1', validators=[SQM_ROI_validator])
    SQM_ROI_X2                       = IntegerField('SQM ROI x2', validators=[SQM_ROI_validator])
    SQM_ROI_Y2                       = IntegerField('SQM ROI y2', validators=[SQM_ROI_validator])
    SQM_FOV_DIV                      = SelectField('SQM FoV', choices=IndiAllskyConfigForm.SQM_FOV_DIV_choices, validators=[SQM_FOV_DIV_validator])
    IMAGE_STACK_METHOD               = SelectField('Image stacking method', choices=IndiAllskyConfigForm.IMAGE_STACK_METHOD_choices, validators=[DataRequired(), IMAGE_STACK_METHOD_validator])
    IMAGE_STACK_COUNT                = SelectField('Stack count', choices=IndiAllskyConfigForm.IMAGE_STACK_COUNT_choices, validators=[DataRequired(), IMAGE_STACK_COUNT_validator])
    IMAGE_STACK_ALIGN                = BooleanField('Register images')
    IMAGE_ALIGN_DETECTSIGMA          = IntegerField('Alignment sensitivity', validators=[DataRequired(), IMAGE_ALIGN_DETECTSIGMA_validator])
    IMAGE_ALIGN_POINTS               = IntegerField('Alignment points', validators=[DataRequired(), IMAGE_ALIGN_POINTS_validator])
    IMAGE_ALIGN_SOURCEMINAREA        = IntegerField('Minimum point area', validators=[DataRequired(), IMAGE_ALIGN_SOURCEMINAREA_validator])
    FISH2PANO__ENABLE                = BooleanField('Fisheye to Panoramic')
    FISH2PANO__DIAMETER              = IntegerField('Diameter', validators=[DataRequired(), FISH2PANO__DIAMETER_validator])
    FISH2PANO__ROTATE_ANGLE          = IntegerField('Rotation Angle', validators=[FISH2PANO__ROTATE_ANGLE_validator])
    FISH2PANO__SCALE                 = FloatField('Scale', validators=[FISH2PANO__SCALE_validator])
    FISH2PANO__FLIP_H                = BooleanField('Flip Horizontally')
    #IMAGE_STACK_SPLIT                = BooleanField('Stack split screen')
    PROCESSING_SPLIT_SCREEN          = BooleanField('Split screen')


class IndiAllskyMiniTimelapseForm(FlaskForm):
    SECONDS_choices = (
        ('60', '1 minute'),
        ('120', '2 minutes'),
        ('180', '3 minutes'),
        ('240', '4 minutes'),
        ('300', '5 minutes'),
        ('360', '6 minutes'),
        ('420', '7 minutes'),
        ('480', '8 minutes'),
        ('540', '9 minutes'),
        ('600', '10 minutes'),
        ('900', '15 minutes'),
        ('1200', '20 minutes'),
        ('1800', '30 minutes'),
        ('2700', '45 minutes'),
        ('3600', '1 hour'),
        ('5400', '1.5 hours'),
        ('7200', '2 hours'),
        ('7200', '2 hours'),
        ('10800', '3 hours'),
        ('14400', '4 hours'),
        ('21600', '6 hours'),
        ('28800', '8 hours'),
        ('43200', '12 hours'),
    )

    FRAMERATE_SELECT_choices = (
        ('0.25', '0.25 FPS'),
        ('0.5', '0.5 FPS'),
        ('0.75', '0.75 FPS'),
        ('1', '1 FPS'),
        ('2', '2 FPS'),
        ('5', '5 FPS'),
        ('10', '10 FPS'),
        ('25', '25 FPS'),
    )

    CAMERA_ID                        = HiddenField('Camera ID', validators=[DataRequired()])
    IMAGE_ID                         = HiddenField('Image ID', validators=[DataRequired()])
    PRE_SECONDS_SELECT               = SelectField('Pre-Selection Time', choices=SECONDS_choices, validators=[DataRequired()])
    POST_SECONDS_SELECT              = SelectField('Post-Selection Time', choices=SECONDS_choices, validators=[DataRequired()])
    FRAMERATE_SELECT                 = SelectField('Speed', choices=FRAMERATE_SELECT_choices, validators=[DataRequired()])
    NOTE                             = StringField('Description', validators=[DataRequired()])


class IndiAllskyLongTermKeogramForm(FlaskForm):
    END_SELECT_choices = (
        ('today', 'Today'),
        ('thisyear', 'End of this year'),
        ('lastyear', 'End of last year'),
    )

    DAYS_SELECT_choices = (
        ('30', '1 Month'),
        ('90', '3 Months'),
        ('180', '6 Months'),
        ('365', '1 Year'),
        ('730', '2 Years'),
        ('1095', '3 Years'),
        ('42', 'All Available'),  # special
    )

    PIXELS_SELECT_choices = (
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
    )

    ALIGNMENT_SELECT_choices = (
        ('20', '20 Seconds'),
        ('30', '30 Seconds'),
        ('40', '40 Seconds'),
        ('50', '50 Seconds'),
        ('60', '60 Seconds'),
        ('75', '75 Seconds'),
        ('90', '90 Seconds'),
        ('120', '120 Seconds'),
    )

    OFFSET_SELECT_choices = (
        ('-43200', '-12'),
        ('-39600', '-11'),
        ('-36000', '-10'),
        ('-32400', '-9'),
        ('-28800', '-8'),
        ('-25200', '-7'),
        ('-21600', '-6'),
        ('-18000', '-5'),
        ('-14400', '-4'),
        ('-10800', '-3'),
        ('-7200', '-2'),
        ('-3600', '-1'),
        ('0', '0'),
        ('3600', '1'),
        ('7200', '2'),
        ('10800', '3'),
        ('14400', '4'),
        ('18000', '5'),
        ('21600', '6'),
        ('25200', '7'),
        ('28800', '8'),
        ('32400', '9'),
        ('36000', '10'),
        ('39600', '11'),
        ('43200', '12'),
    )

    CAMERA_ID               = HiddenField('Camera ID', validators=[DataRequired()])
    END_SELECT              = SelectField('Start', choices=END_SELECT_choices, default=END_SELECT_choices[0][0], validators=[DataRequired()])
    DAYS_SELECT             = SelectField('Timeframe', choices=DAYS_SELECT_choices, default=DAYS_SELECT_choices[0][0], validators=[DataRequired()])
    PIXELS_SELECT           = SelectField('Pixels per Day', choices=PIXELS_SELECT_choices, default=PIXELS_SELECT_choices[4][0], validators=[DataRequired()])
    ALIGNMENT_SELECT        = SelectField('Alignment', choices=ALIGNMENT_SELECT_choices, default=ALIGNMENT_SELECT_choices[4][0], validators=[DataRequired()])
    OFFSET_SELECT           = SelectField('Hour Offset', choices=OFFSET_SELECT_choices, default=OFFSET_SELECT_choices[12][0], validators=[DataRequired()])


class IndiAllskyCameraSimulatorForm(FlaskForm):
    SENSOR_SELECT_choices = {
        'Small' : (
            ('imx219', 'IMX219 - 1/4" - Camera Module 2'),
            ('imx415_sv205', 'SV205C - 1/2.8" (IMX415)'),
            ('ov5647', 'OV5647 - 1/4" - Camera Module 1'),
        ),
        'Medium - 6mm Class' : (
            ('ar0130', 'ASI120 - 1/3" - AR0130CS'),
            ('imx224', 'IMX224 - 1/3"'),
            ('imx225', 'IMX225 - 1/3"'),
            ('imx273', 'IMX273 - 1/2.9"'),
            ('imx287', 'IMX287 - 1/2.9"'),
            ('imx290', 'IMX290 - 1/2.8"'),
            ('imx296', 'IMX296 - 1/2.9" - Global Shutter'),
            ('imx298', 'IMX298 - 1/2.8"'),
            ('imx307', 'IMX307 - 1/2.8" - SV105C'),
            ('imx327', 'IMX327 - 1/2.8"'),
            ('imx415', 'IMX415 - 1/2.8"'),
            ('imx462', 'IMX462 - 1/2.8"'),
            ('imx662', 'IMX662 - 1/2.8"'),
            ('imx715', 'IMX715 - 1/2.8"'),
            ('mt9m034', 'QHY5LII - 1/3" - MT9M034'),
        ),
        'Medium - 7mm Class' : (
            ('ar0234', 'AR0234 - 1/2.6" - Global Shutter'),
            ('imx230', 'IMX230 - 1/2.4"'),
            ('imx519', 'IMX519 - 1/2.53"'),
            ('imx708', 'IMX708 - 1/2.43" - Camera Module 3'),
        ),
        'Medium - 8mm Class' : (
            ('imx185', 'IMX185 - 1/1.9"'),
            ('imx378', 'IMX378 - 1/2.3"'),
            ('imx385', 'IMX385 - 1/1.9"'),
            ('imx477', 'IMX477 - 1/2.3" - HQ Camera'),
            ('icx205al', 'ICX205AL - 1/2" - SX Superstar'),
            ('mt9t001', 'MT9T001 - 1/2"'),
        ),
        'Medium - 9mm Class' : (
            ('icx274al', 'ICX274AL - 1/1.8"'),
            ('imx178', 'IMX178 - 1/1.8"'),
            ('imx252', 'IMX252 - 1/1.8"'),
            ('imx265', 'IMX265 - 1/1.8"'),
            ('imx464', 'IMX464 - 1/1.8" - POA Neptune-C II'),
            ('imx664', 'IMX664 - 1/1.8" - POA Neptune 664C'),
            ('imx678', 'IMX678 - 1/1.8"'),
            ('imx682', 'IMX682 - 1/1.7" - 64MP Hawkeye'),
            ('sc2210', 'SC2210 - 1/1.8" - ASI220'),
        ),
        'Medium - 10-13mm Class' : (
            ('ov64a40', 'OV64A40 - 1/1.32 - 64MP OwlSight'),
            ('imx250', 'IMX250 - 2/3"'),
            ('imx264', 'IMX264 - 2/3"'),
            ('imx429', 'IMX429 - 2/3" - POA Apollo-M MINI'),
            ('imx482', 'IMX482 - 1/1.2"'),
            ('imx485', 'IMX485 - 1/1.2"'),
            ('imx585', 'IMX585 - 1/1.2"'),
            ('imx676', 'IMX676 - 1/1.6"'),
            ('icx825al', 'ICX825AL - 2/3" - SX ULTRASTAR PRO'),
        ),
        'Large' : (
            ('imx174', 'IMX174 - 1/1.2"'),
            ('imx183', 'IMX183 - 1"'),
            ('imx249', 'IMX249 - 1/1.2" - POA Xena-M'),
            ('imx253', 'IMX253 - 1.1"'),
            ('imx283', 'IMX283 - 1" - Arducam Klarity'),
            ('imx304', 'IMX304 - 1.1"'),
            ('imx432', 'IMX432 - 1.1"'),
            ('imx533', 'IMX533 - 1"'),
        ),
        'Extra Large' : (
            ('imx269', 'IMX269 - 4/3"'),
            ('imx294', 'IMX294 - 4/3"'),
            ('imx410', 'IMX410 - Full Frame - ASI2400'),
            ('imx455', 'IMX455 - Full Frame - ASI6200'),
            ('imx571', 'IMX571 - APS-C - ASI2600'),
        ),
    }

    LENS_SELECT_choices = {
        'Small' : (
            ('m12_f2.1_0.76mm_1-3.2', 'M12 0.76mm ƒ/2.1 - 222° - 1/3.2" ∅2.77mm'),
            ('m12_f2.2_1.71mm_1-3', 'M12 1.71mm ƒ/2.2 - 184° - 1/3" ∅3.5mm'),
            ('m12_f2.0_1.44mm_1-2.5', 'M12 1.44mm ƒ/2.0 - 180° - 1/2.5" ∅3.55mm'),
        ),
        'Medium' : (
            ('fe185c046ha_f1.4_1.4mm_1-2', 'Fujinon 1.4mm ƒ/1.4 - 185° - 1/2" ∅4.6mm'),
            ('arecont_f2.0_1.55mm_1-2', 'Arecont 1.55mm ƒ/2.0 - 180° - 1/2" ∅4.8mm'),
            ('stardot_f1.5_1.55mm_1-2', 'Stardot 1.55mm ƒ/1.5 - 180° - 1/2" ∅4.8mm'),
            ('m12_f2.4_1.8mm_1-4', 'M12 1.8mm ƒ/2.4 - 125° - 1/4" ∅4.8mm'),
            ('m12_f2.0_1.56mm_1-2.5', 'M12 1.56mm ƒ/2.0 - 185° - 1/2.5" ∅4.8mm'),
            ('m12_f2.0_1.7mm_1-2.5', 'M12 1.7mm ƒ/2.0 - 180° - 1/2.5" ∅5.6mm'),
            ('fe185c057ha_f1.4_1.8mm_2-3', 'Fujinon 1.8mm ƒ/1.4 - 185° - 2/3" ∅5.7mm'),
            ('m12_f2.0_1.85mm_1-1.8', 'M12 1.85mm ƒ/2.0 - 180° - 1/1.8" ∅5.8mm'),
            ('cs-2.5ir_8mp_-f_f1.6_2.5mm_2-3', 'CS-2.5IR(8MP)-F 2.5mm ƒ/1.6 - 190° - 2/3 ∅6.4mm'),
            ('zwo_f2.0_2.1mm_1-3', 'ZWO 2.1mm ƒ/2.0 - 150° - 1/3" ∅6.7mm'),
            ('zwo_f1.2_2.5mm_1-2', 'ZWO 2.5mm ƒ/1.2 - 170° - 1/2" ∅6.7mm'),
            ('m12_f2.0_2.1mm_1-2.7', 'M12 2.1mm ƒ/2.0 - 170° - 1/2.7" ∅6.7mm'),
            ('m12_f2.0_1.8mm_1-2.5', 'M12 1.8mm ƒ/2.0 - 180° - 1/2.5" ∅6.9mm'),
        ),
        'Large' : (
            ('fe185c086ha_f1.8_2.7mm_1', 'Fujinon 2.7mm ƒ/1.8 - 185° - 1" ∅8.6mm'),
            ('vm2.8ir10mp_f1.6_2.8mm_1-1.8', 'VM2.8IR10MP 2.8mm ƒ/1.6 - 190° - 1/1.8" ∅9.0mm'),
            ('meike_f2.8_3.5mm_4-3', 'Meike 3.5mm ƒ/2.8 Fisheye - 220° - 4/3" ∅12.5mm'),
            ('7artisans_f2.8_4.0mm_4-3', '7Artisans 4mm ƒ/2.8 Fisheye - 225° - 4/3" ∅12.37mm'),
            ('laowa_f2.8_4.0mm_4-3', 'Laowa 4mm ƒ/2.8 Fisheye - 210° - 4/3 ∅13.4mm'),
            ('custom_f7_5.8mm_m42', 'Custom 5.8mm ƒ/7 - 174° - ∅17.3mm'),
        ),
    }

    SENSOR_SELECT     = SelectField('Sensor', choices=SENSOR_SELECT_choices)
    LENS_SELECT       = SelectField('Lens', choices=LENS_SELECT_choices)
    OFFSET_X          = IntegerField('X Offset', default=0, render_kw={'step' : '25'})
    OFFSET_Y          = IntegerField('Y Offset', default=0, render_kw={'step' : '25'})
