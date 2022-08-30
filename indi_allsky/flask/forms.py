import os
from pathlib import Path
import io
import re
import json
import time
from datetime import datetime
import subprocess
import cv2
import numpy

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

from sqlalchemy import extract
#from sqlalchemy import asc
from sqlalchemy import func
#from sqlalchemy.types import DateTime
#from sqlalchemy.types import Date
#from sqlalchemy.orm.exc import NoResultFound

from flask import current_app as app

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable

from . import db


def SQLALCHEMY_DATABASE_URI_validator(form, field):
    host_regex = r'^[a-zA-Z0-9_\.\-\:\/\@]+$'

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid URI')


def CAMERA_INTERFACE_validator(form, field):
    if field.data not in ('indi', 'libcamera_imx477'):
        raise ValidationError('Invalid camera interface')


def INDI_SERVER_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9\.\-]+$'

    if not re.search(host_regex, field.data):
        raise ValidationError('Invalid host name')


def INDI_PORT_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Port must be 0 or greater')

    if field.data > 65535:
        raise ValidationError('Port must be less than 65535')


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

    if field.data > 60.0:
        raise ValidationError('Max Exposure cannot be more than 60')


def CCD_EXPOSURE_DEF_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Default Exposure must be 0 or more')

    if field.data > 60.0:
        raise ValidationError('Default Exposure cannot be more than 60')


def CCD_EXPOSURE_MIN_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Minimum Exposure must be 0 or more')

    if field.data > 60.0:
        raise ValidationError('Minimum Exposure cannot be more than 60')


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


def FOCUS_DELAY_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 1.0:
        raise ValidationError('Focus delay must be 1.0 or more')


def WB_FACTOR_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data < 0.0:
        raise ValidationError('Balance factor must be 0 or greater')

    if field.data > 2.0:
        raise ValidationError('Balance factor must be less than 2.0')


def TEMP_DISPLAY_validator(form, field):
    if field.data not in ('c', 'f', 'k'):
        raise ValidationError('Please select the temperature system for display')


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


    cmd = [
        str(temp_script_p),
    ]

    try:
        temp_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise ValidationError('Temperature script failed to execute')


    try:
        temp_process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        temp_process.kill()
        time.sleep(1.0)
        temp_process.poll()  # close out process
        raise ValidationError('Temperature script timed out')


    if temp_process.returncode != 0:
        raise ValidationError('Temperature script returned exited abnormally')


    temp_str = temp_process.stdout.readline()  # temp should be on the first line of output


    try:
        float(temp_str.rstrip())
    except ValueError:
        raise ValidationError('Temperature script returned a non-numerical value')


def TARGET_ADU_validator(form, field):
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


def DETECT_STARS_THOLD_validator(form, field):
    if not isinstance(field.data, (int, float)):
        raise ValidationError('Please enter valid number')

    if field.data <= 0.0:
        raise ValidationError('Threshold must be greater than 0')

    if field.data > 1.0:
        raise ValidationError('Threshold must be 1.0 or less')


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


def IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in ('jpg', 'png', 'tif'):
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


def IMAGE_FILE_COMPRESSION__TIF_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')


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

    if field.data not in ('png', 'tif'):
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


def IMAGE_SCALE_validator(form, field):
    if field.data < 1:
        raise ValidationError('Image Scaling must be 1 or greater')

    if field.data > 100:
        raise ValidationError('Image Scaling must be 100 or less')


def IMAGE_CROP_ROI_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Crop Region of Interest must be 0 or greater')


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

    if field.data > 50:
        raise ValidationError('FFMPEG frame rate must be 50 or less')


def FFMPEG_BITRATE_validator(form, field):
    bitrate_regex = r'^\d+[km]$'

    if not re.search(bitrate_regex, field.data):
        raise ValidationError('Invalid bitrate syntax')


def FFMPEG_VFSCALE_validator(form, field):
    if not field.data:
        return

    scale_regex = r'^[\-?\d+\:\-?\d+]+$'
    if not re.search(scale_regex, field.data):
        raise ValidationError('Invalid scale option')


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


def TEXT_PROPERTIES__DATE_FORMAT_validator(form, field):
    format_regex = r'^[a-zA-Z0-9_,\%\.\-\/\\\:\ ]+$'

    if not re.search(format_regex, field.data):
        raise ValidationError('Invalid datetime format')

    try:
        # test the format
        now = datetime.now()
        now.strftime(field.data)
    except ValueError as e:
        raise ValidationError(str(e))


def ORB_PROPERTIES__MODE_validator(form, field):
    if field.data not in ('ha', 'az', 'alt', 'off'):
        raise ValidationError('Please select a valid orb mode')


def ORB_PROPERTIES__RADIUS_validator(form, field):
    if field.data < 1:
        raise ValidationError('Orb radius must be 1 or more')


def FILETRANSFER__CLASSNAME_validator(form, field):
    class_names = (
        'pycurl_sftp',
        'paramiko_sftp',
        'pycurl_ftpes',
        'pycurl_ftps',
        'pycurl_ftp',
        'python_ftp',
        'python_ftpes',
        'pycurl_webdav_https',
    )

    if field.data not in class_names:
        raise ValidationError('Invalid selection')


def FILETRANSFER__HOST_validator(form, field):
    if not field.data:
        return

    host_regex = r'^[a-zA-Z0-9\.\-]+$'

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

    host_regex = r'^[a-zA-Z0-9\.\-]+$'

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

    username_regex = r'^[a-zA-Z0-9_\@\.\-\\]+$'

    if not re.search(username_regex, field.data):
        raise ValidationError('Invalid username')


def FILETRANSFER__PASSWORD_validator(form, field):
    pass


def MQTTPUBLISH__PASSWORD_validator(form, field):
    pass


def FILETRANSFER__TIMEOUT_validator(form, field):
    if field.data < 1:
        raise ValidationError('Timeout must be 1.0 or greater')

    if field.data > 60:
        raise ValidationError('Timeout must be 60 or less')


def FILETRANSFER__REMOTE_IMAGE_NAME_validator(form, field):
    image_name_regex = r'^[a-zA-Z0-9_\.\-\{\}]+$'

    if not re.search(image_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


def FILETRANSFER__REMOTE_METADATA_NAME_validator(form, field):
    metadata_name_regex = r'^[a-zA-Z0-9_\.\-]+$'

    if not re.search(metadata_name_regex, field.data):
        raise ValidationError('Invalid filename syntax')


def REMOTE_FOLDER_validator(form, field):
    folder_regex = r'^[a-zA-Z0-9_\.\-\/]+$'

    if not re.search(folder_regex, field.data):
        raise ValidationError('Invalid filename syntax')


def UPLOAD_IMAGE_validator(form, field):
    if not isinstance(field.data, int):
        raise ValidationError('Please enter valid number')

    if field.data < 0:
        raise ValidationError('Image Upload must be 0 or greater')


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


def LIBCAMERA__IMAGE_FILE_TYPE_validator(form, field):
    if field.data not in ('dng', 'jpg', 'png'):
        raise ValidationError('Please select a valid file type')


def INDI_CONFIG_DEFAULTS_validator(form, field):
    try:
        json_data = json.loads(field.data)
    except json.decoder.JSONDecodeError as e:
        raise ValidationError(str(e))


    for k in json_data.keys():
        if k not in ('PROPERTIES', 'SWITCHES'):
            raise ValidationError('Only PROPERTIES and SWITCHES attributes allowed')

    try:
        json_data['PROPERTIES']
    except KeyError:
        raise ValidationError('PROPERTIES attribute missing')

    try:
        json_data['SWITCHES']
    except KeyError:
        raise ValidationError('SWITCHES attribute missing')


    for k, v in json_data['SWITCHES'].items():
        for k2 in v.keys():
            if k2 not in ('on', 'off'):
                raise ValidationError('Invalid switch configuration {0:s}'.format(k2))



class IndiAllskyConfigForm(FlaskForm):
    CAMERA_INTERFACE_choices = (
        ('indi', 'INDI'),
        ('libcamera_imx477', 'libcamera IMX477'),
    )

    TEMP_DISPLAY_choices = (
        ('c', 'Celcius'),
        ('f', 'Fahrenheit'),
        ('k', 'Kelvin'),
    )

    IMAGE_FILE_TYPE_choices = (
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
        ('tif', 'TIFF'),
    )

    IMAGE_EXPORT_RAW_choices = (
        ('', 'Disabled'),
        ('png', 'PNG'),
        ('tif', 'TIFF'),
    )

    FFMPEG_VFSCALE_choices = (
        ('', 'None'),
        ('-1:2304', 'V 2304px (imx477)'),
    )

    ORB_PROPERTIES__MODE_choices = (
        ('ha', 'Hour Angle'),
        ('az', 'Azimuth'),
        ('alt', 'Altitude'),
        ('off', 'Off'),
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

    FILETRANSFER__CLASSNAME_choices = (
        ('pycurl_sftp', 'PycURL SFTP [22]'),
        ('paramiko_sftp', 'Paramiko SFTP [22]'),
        ('pycurl_ftpes', 'PycURL FTPES [21]'),
        ('pycurl_ftps', 'PycURL FTPS [990]'),
        ('pycurl_ftp', 'PycURL FTP [21] *no encryption*'),
        ('python_ftp', 'Python FTP [21] *no encryption*'),
        ('python_ftpes', 'Python FTPES [21]'),
        ('pycurl_webdav_https', 'PycURL WebDAV HTTPS [443]'),
    )

    MQTTPUBLISH__TRANSPORT_choices = (
        ('tcp', 'tcp'),
        ('websockets', 'websockets'),
    )

    LIBCAMERA__IMAGE_FILE_TYPE_choices = (
        ('dng', 'DNG (raw)'),
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
    )


    SQLALCHEMY_DATABASE_URI          = StringField('Database URI', render_kw={'readonly' : True}, validators=[DataRequired(), SQLALCHEMY_DATABASE_URI_validator])
    CAMERA_INTERFACE                 = SelectField('Camera Interface', choices=CAMERA_INTERFACE_choices, validators=[DataRequired(), CAMERA_INTERFACE_validator])
    INDI_SERVER                      = StringField('INDI Server', validators=[DataRequired(), INDI_SERVER_validator])
    INDI_PORT                        = IntegerField('INDI port', validators=[DataRequired(), INDI_PORT_validator])
    CCD_CONFIG__NIGHT__GAIN          = IntegerField('Night Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__NIGHT__BINNING       = IntegerField('Night Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__MOONMODE__GAIN       = IntegerField('Moon Mode Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__MOONMODE__BINNING    = IntegerField('Moon Mode Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__DAY__GAIN            = IntegerField('Daytime Gain', validators=[ccd_GAIN_validator])
    CCD_CONFIG__DAY__BINNING         = IntegerField('Daytime Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_EXPOSURE_MAX                 = FloatField('Max Exposure', validators=[DataRequired(), CCD_EXPOSURE_MAX_validator])
    CCD_EXPOSURE_DEF                 = FloatField('Default Exposure', validators=[CCD_EXPOSURE_DEF_validator])
    CCD_EXPOSURE_MIN                 = FloatField('Min Exposure', validators=[CCD_EXPOSURE_MIN_validator])
    EXPOSURE_PERIOD                  = FloatField('Exposure Period (Night)', validators=[DataRequired(), EXPOSURE_PERIOD_validator])
    EXPOSURE_PERIOD_DAY              = FloatField('Exposure Period (Day)', validators=[DataRequired(), EXPOSURE_PERIOD_DAY_validator])
    FOCUS_MODE                       = BooleanField('Focus Mode')
    FOCUS_DELAY                      = FloatField('Focus Delay', validators=[DataRequired(), FOCUS_DELAY_validator])
    AUTO_WB                          = BooleanField('Auto White Balance')
    WBR_FACTOR                       = FloatField('Red Balance Factor', validators=[DataRequired(), WB_FACTOR_validator])
    WBG_FACTOR                       = FloatField('Green Balance Factor', validators=[DataRequired(), WB_FACTOR_validator])
    WBB_FACTOR                       = FloatField('Blue Balance Factor', validators=[DataRequired(), WB_FACTOR_validator])
    TEMP_DISPLAY                     = SelectField('Temperature Display', choices=TEMP_DISPLAY_choices, validators=[DataRequired(), TEMP_DISPLAY_validator])
    CCD_TEMP_SCRIPT                  = StringField('External Temperature Script', validators=[CCD_TEMP_SCRIPT_validator])
    TARGET_ADU                       = IntegerField('Target ADU', validators=[DataRequired(), TARGET_ADU_validator])
    TARGET_ADU_DEV                   = IntegerField('Target ADU Deviation (night)', validators=[DataRequired(), TARGET_ADU_DEV_validator])
    TARGET_ADU_DEV_DAY               = IntegerField('Target ADU Deviation (day)', validators=[DataRequired(), TARGET_ADU_DEV_DAY_validator])
    ADU_ROI_X1                       = IntegerField('ADU ROI x1', validators=[ADU_ROI_validator])
    ADU_ROI_Y1                       = IntegerField('ADU ROI y1', validators=[ADU_ROI_validator])
    ADU_ROI_X2                       = IntegerField('ADU ROI x2', validators=[ADU_ROI_validator])
    ADU_ROI_Y2                       = IntegerField('ADU ROI y2', validators=[ADU_ROI_validator])
    DETECT_STARS                     = BooleanField('Star Detection')
    DETECT_STARS_THOLD               = FloatField('Star Detection Threshold', validators=[DataRequired(), DETECT_STARS_THOLD_validator])
    DETECT_METEORS                   = BooleanField('Meteor Detection')
    DETECT_MASK                      = StringField('Detection Mask', validators=[DETECT_MASK_validator])
    DETECT_DRAW                      = BooleanField('Mark Detections on Image')
    SQM_ROI_X1                       = IntegerField('SQM ROI x1', validators=[SQM_ROI_validator])
    SQM_ROI_Y1                       = IntegerField('SQM ROI y1', validators=[SQM_ROI_validator])
    SQM_ROI_X2                       = IntegerField('SQM ROI x2', validators=[SQM_ROI_validator])
    SQM_ROI_Y2                       = IntegerField('SQM ROI y2', validators=[SQM_ROI_validator])
    LOCATION_LATITUDE                = FloatField('Latitude', validators=[LOCATION_LATITUDE_validator])
    LOCATION_LONGITUDE               = FloatField('Longitude', validators=[LOCATION_LONGITUDE_validator])
    TIMELAPSE_ENABLE                 = BooleanField('Enable Timelapse Creation')
    DAYTIME_CAPTURE                  = BooleanField('Daytime Capture')
    DAYTIME_TIMELAPSE                = BooleanField('Daytime Timelapse')
    DAYTIME_CONTRAST_ENHANCE         = BooleanField('Daytime Contrast Enhance')
    NIGHT_CONTRAST_ENHANCE           = BooleanField('Night time Contrast Enhance')
    NIGHT_SUN_ALT_DEG                = FloatField('Sun altitude', validators=[NIGHT_SUN_ALT_DEG_validator])
    NIGHT_MOONMODE_ALT_DEG           = FloatField('Moonmode Moon Altitude', validators=[NIGHT_MOONMODE_ALT_DEG_validator])
    NIGHT_MOONMODE_PHASE             = FloatField('Moonmode Moon Phase', validators=[NIGHT_MOONMODE_PHASE_validator])
    WEB_EXTRA_TEXT                   = StringField('Extra HTML Info File', validators=[WEB_EXTRA_TEXT_validator])
    KEOGRAM_ANGLE                    = FloatField('Keogram Rotation Angle', validators=[KEOGRAM_ANGLE_validator])
    KEOGRAM_H_SCALE                  = IntegerField('Keogram Horizontal Scaling', validators=[DataRequired(), KEOGRAM_H_SCALE_validator])
    KEOGRAM_V_SCALE                  = IntegerField('Keogram Vertical Scaling', validators=[DataRequired(), KEOGRAM_V_SCALE_validator])
    KEOGRAM_LABEL                    = BooleanField('Label Keogram')
    STARTRAILS_MAX_ADU               = IntegerField('Star Trails Max ADU', validators=[DataRequired(), STARTRAILS_MAX_ADU_validator])
    STARTRAILS_MASK_THOLD            = IntegerField('Star Trails Mask Threshold', validators=[DataRequired(), STARTRAILS_MASK_THOLD_validator])
    STARTRAILS_PIXEL_THOLD           = FloatField('Star Trails Pixel Threshold', validators=[STARTRAILS_PIXEL_THOLD_validator])
    IMAGE_FILE_TYPE                  = SelectField('Image file type', choices=IMAGE_FILE_TYPE_choices, validators=[DataRequired(), IMAGE_FILE_TYPE_validator])
    IMAGE_FILE_COMPRESSION__JPG      = IntegerField('JPEG Compression', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__JPG_validator])
    IMAGE_FILE_COMPRESSION__PNG      = IntegerField('PNG Compression', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__PNG_validator])
    IMAGE_FILE_COMPRESSION__TIF      = IntegerField('TIFF Compression', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__TIF_validator])
    IMAGE_FOLDER                     = StringField('Image folder', validators=[DataRequired(), IMAGE_FOLDER_validator])
    IMAGE_LABEL                      = BooleanField('Label Images')
    IMAGE_EXTRA_TEXT                 = StringField('Extra Image Text File', validators=[IMAGE_EXTRA_TEXT_validator])
    IMAGE_FLIP_V                     = BooleanField('Flip Image Vertically')
    IMAGE_FLIP_H                     = BooleanField('Flip Image Horizontally')
    IMAGE_SCALE                      = IntegerField('Image Scaling', validators=[DataRequired(), IMAGE_SCALE_validator])
    IMAGE_CROP_ROI_X1                = IntegerField('Image Crop ROI x1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y1                = IntegerField('Image Crop ROI y1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_X2                = IntegerField('Image Crop ROI x2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y2                = IntegerField('Image Crop ROI y2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_SAVE_FITS                  = BooleanField('Save FITS data')
    NIGHT_GRAYSCALE                  = BooleanField('Save in Grayscale at Night')
    DAYTIME_GRAYSCALE                = BooleanField('Save in Grayscale during Day')
    IMAGE_EXPORT_RAW                 = SelectField('Export raw image type', choices=IMAGE_EXPORT_RAW_choices, validators=[IMAGE_EXPORT_RAW_validator])
    IMAGE_EXPORT_FOLDER              = StringField('Export folder', validators=[DataRequired(), IMAGE_EXPORT_FOLDER_validator])
    IMAGE_EXPIRE_DAYS                = IntegerField('Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    TIMELAPSE_EXPIRE_DAYS            = IntegerField('Timelapse expiration (days)', validators=[DataRequired(), TIMELAPSE_EXPIRE_DAYS_validator])
    FFMPEG_FRAMERATE                 = IntegerField('FFMPEG Framerate', validators=[DataRequired(), FFMPEG_FRAMERATE_validator])
    FFMPEG_BITRATE                   = StringField('FFMPEG Bitrate', validators=[DataRequired(), FFMPEG_BITRATE_validator])
    FFMPEG_VFSCALE                   = SelectField('FFMPEG Scaling', choices=FFMPEG_VFSCALE_choices, validators=[FFMPEG_VFSCALE_validator])
    TEXT_PROPERTIES__FONT_FACE       = SelectField('Font', choices=TEXT_PROPERTIES__FONT_FACE_choices, validators=[DataRequired(), TEXT_PROPERTIES__FONT_FACE_validator])
    TEXT_PROPERTIES__FONT_HEIGHT     = IntegerField('Font Height Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_HEIGHT_validator])
    TEXT_PROPERTIES__FONT_X          = IntegerField('Font X Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_X_validator])
    TEXT_PROPERTIES__FONT_Y          = IntegerField('Font Y Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_Y_validator])
    TEXT_PROPERTIES__FONT_COLOR      = StringField('Font Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    #TEXT_PROPERTIES__FONT_AA
    TEXT_PROPERTIES__FONT_SCALE      = FloatField('Font Scale', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    TEXT_PROPERTIES__FONT_THICKNESS  = IntegerField('Font Thickness', validators=[DataRequired(), TEXT_PROPERTIES__FONT_THICKNESS_validator])
    TEXT_PROPERTIES__FONT_OUTLINE    = BooleanField('Font Outline')
    TEXT_PROPERTIES__DATE_FORMAT     = StringField('Date Format', validators=[DataRequired(), TEXT_PROPERTIES__DATE_FORMAT_validator])
    ORB_PROPERTIES__MODE             = SelectField('Orb Mode', choices=ORB_PROPERTIES__MODE_choices, validators=[DataRequired(), ORB_PROPERTIES__MODE_validator])
    ORB_PROPERTIES__RADIUS           = IntegerField('Orb Radius', validators=[DataRequired(), ORB_PROPERTIES__RADIUS_validator])
    ORB_PROPERTIES__SUN_COLOR        = StringField('Sun Orb Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    ORB_PROPERTIES__MOON_COLOR       = StringField('Moon Orb Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    FILETRANSFER__CLASSNAME          = SelectField('Protocol', choices=FILETRANSFER__CLASSNAME_choices, validators=[DataRequired(), FILETRANSFER__CLASSNAME_validator])
    FILETRANSFER__HOST               = StringField('Host', validators=[FILETRANSFER__HOST_validator])
    FILETRANSFER__PORT               = IntegerField('Port', validators=[FILETRANSFER__PORT_validator])
    FILETRANSFER__USERNAME           = StringField('Username', validators=[FILETRANSFER__USERNAME_validator])
    FILETRANSFER__PASSWORD           = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[FILETRANSFER__PASSWORD_validator])
    FILETRANSFER__TIMEOUT            = FloatField('Timeout', validators=[DataRequired(), FILETRANSFER__TIMEOUT_validator])
    FILETRANSFER__REMOTE_IMAGE_NAME  = StringField('Remote Image Name', validators=[DataRequired(), FILETRANSFER__REMOTE_IMAGE_NAME_validator])
    FILETRANSFER__REMOTE_IMAGE_FOLDER      = StringField('Remote Image Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_METADATA_NAME     = StringField('Remote Metadata Name', validators=[DataRequired(), FILETRANSFER__REMOTE_METADATA_NAME_validator])
    FILETRANSFER__REMOTE_METADATA_FOLDER   = StringField('Remote Metadata Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_VIDEO_FOLDER      = StringField('Remote Video Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_KEOGRAM_FOLDER    = StringField('Remote Keogram Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_STARTRAIL_FOLDER  = StringField('Remote Star Trails Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER = StringField('Remote EndOfNight Folder', validators=[DataRequired(), REMOTE_FOLDER_validator])
    FILETRANSFER__UPLOAD_IMAGE       = IntegerField('Transfer images', validators=[UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_METADATA    = BooleanField('Transfer metadata')
    FILETRANSFER__UPLOAD_VIDEO       = BooleanField('Transfer videos')
    FILETRANSFER__UPLOAD_KEOGRAM     = BooleanField('Transfer keograms')
    FILETRANSFER__UPLOAD_STARTRAIL   = BooleanField('Transfer star trails')
    FILETRANSFER__UPLOAD_ENDOFNIGHT  = BooleanField('Transfer AllSky EndOfNight data')
    MQTTPUBLISH__ENABLE              = BooleanField('Enable MQTT Publishing')
    MQTTPUBLISH__TRANSPORT           = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    MQTTPUBLISH__HOST                = StringField('MQTT Host', validators=[MQTTPUBLISH__HOST_validator])
    MQTTPUBLISH__PORT                = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    MQTTPUBLISH__USERNAME            = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator])
    MQTTPUBLISH__PASSWORD            = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator])
    MQTTPUBLISH__BASE_TOPIC          = StringField('MQTT Base Topic', validators=[DataRequired(), MQTTPUBLISH__BASE_TOPIC_validator])
    MQTTPUBLISH__QOS                 = IntegerField('MQTT QoS', validators=[MQTTPUBLISH__QOS_validator])
    MQTTPUBLISH__TLS                 = BooleanField('Use TLS')
    MQTTPUBLISH__CERT_BYPASS         = BooleanField('Disable Certificate Validation')
    LIBCAMERA__IMAGE_FILE_TYPE       = SelectField('libcamera image type', choices=LIBCAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), LIBCAMERA__IMAGE_FILE_TYPE_validator])
    INDI_CONFIG_DEFAULTS             = TextAreaField('INDI Configuration', validators=[DataRequired(), INDI_CONFIG_DEFAULTS_validator])


    #def __init__(self, *args, **kwargs):
    #    super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)


class IndiAllskyImageViewer(FlaskForm):
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    IMG_SELECT           = SelectField('Image', choices=[], validators=[])
    FILTER_DETECTIONS    = BooleanField('Detections')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewer, self).__init__(*args, **kwargs)

        self.detections_count = kwargs.get('detections_count', 0)


    def getYears(self):
        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        createDate_year = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_year')

        years_query = db.session.query(
            createDate_year,
        )\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
            .distinct()\
            .order_by(createDate_year.desc())

        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        createDate_year = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_year')
        createDate_month = extract('month', IndiAllSkyDbImageTable.createDate).label('createDate_month')

        months_query = db.session.query(
            createDate_year,
            createDate_month,
        )\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
            .filter(createDate_year == year)\
            .distinct()\
            .order_by(createDate_month.desc())

        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        createDate_year = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_year')
        createDate_month = extract('month', IndiAllSkyDbImageTable.createDate).label('createDate_month')
        createDate_day = extract('day', IndiAllSkyDbImageTable.createDate).label('createDate_day')

        days_query = db.session.query(
            createDate_year,
            createDate_month,
            createDate_day,
        )\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
            .filter(createDate_year == year)\
            .filter(createDate_month == month)\
            .distinct()\
            .order_by(createDate_day.desc())

        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        createDate_year = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_year')
        createDate_month = extract('month', IndiAllSkyDbImageTable.createDate).label('createDate_month')
        createDate_day = extract('day', IndiAllSkyDbImageTable.createDate).label('createDate_day')
        createDate_hour = extract('hour', IndiAllSkyDbImageTable.createDate).label('createDate_hour')

        hours_query = db.session.query(
            createDate_year,
            createDate_month,
            createDate_day,
            createDate_hour,
        )\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
            .filter(createDate_year == year)\
            .filter(createDate_month == month)\
            .filter(createDate_day == day)\
            .distinct()\
            .order_by(createDate_hour.desc())

        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        createDate_year = extract('year', IndiAllSkyDbImageTable.createDate).label('createDate_year')
        createDate_month = extract('month', IndiAllSkyDbImageTable.createDate).label('createDate_month')
        createDate_day = extract('day', IndiAllSkyDbImageTable.createDate).label('createDate_day')
        createDate_hour = extract('hour', IndiAllSkyDbImageTable.createDate).label('createDate_hour')

        images_query = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
            .filter(createDate_year == year)\
            .filter(createDate_month == month)\
            .filter(createDate_day == day)\
            .filter(createDate_hour == hour)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())

        images_choices = []
        for i in images_query:
            try:
                uri = i.getUri()
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            if i.detections:
                entry_str = '{0:s} [*]'.format(i.createDate.strftime('%H:%M:%S'))
            else:
                entry_str = i.createDate.strftime('%H:%M:%S')

            entry = (str(uri), entry_str)

            images_choices.append(entry)


        return images_choices




class IndiAllskyImageViewerPreload(IndiAllskyImageViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewerPreload, self).__init__(*args, **kwargs)

        last_image = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.detections >= self.detections_count)\
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


        year = last_image.createDate.strftime('%Y')
        month = last_image.createDate.strftime('%m')
        day = last_image.createDate.strftime('%d')
        hour = last_image.createDate.strftime('%H')


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = self.getMonths(year)
        self.DAY_SELECT.choices = self.getDays(year, month)
        self.HOUR_SELECT.choices = self.getHours(year, month, day)
        self.IMG_SELECT.choices = self.getImages(year, month, day, hour)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)



class IndiAllskyVideoViewer(FlaskForm):
    TIMEOFDAY_SELECT_choices = (
        ('all', 'All'),
        ('day', 'Day'),
        ('night', 'Night'),
    )

    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    TIMEOFDAY_SELECT     = SelectField('Time of Day', choices=TIMEOFDAY_SELECT_choices, validators=[])


    def getYears(self):
        dayDate_year = extract('year', IndiAllSkyDbVideoTable.dayDate).label('dayDate_year')

        years_query = db.session.query(
            dayDate_year,
        )\
            .distinct()\
            .order_by(dayDate_year.desc())

        year_choices = []
        for y in years_query:
            entry = (y.dayDate_year, str(y.dayDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        dayDate_year = extract('year', IndiAllSkyDbVideoTable.dayDate).label('dayDate_year')
        dayDate_month = extract('month', IndiAllSkyDbVideoTable.dayDate).label('dayDate_month')

        months_query = db.session.query(
            dayDate_year,
            dayDate_month,
        )\
            .filter(dayDate_year == year)\
            .distinct()\
            .order_by(dayDate_month.desc())

        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.dayDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.dayDate_month, month_name)
            month_choices.append(entry)


        return month_choices



    def getVideos(self, year, month, timeofday):
        dayDate_year = extract('year', IndiAllSkyDbVideoTable.dayDate).label('dayDate_year')
        dayDate_month = extract('month', IndiAllSkyDbVideoTable.dayDate).label('dayDate_month')

        videos_query = IndiAllSkyDbVideoTable.query\
            .filter(dayDate_year == year)\
            .filter(dayDate_month == month)


        # add time of day filter
        if timeofday == 'day':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == False)  # noqa: E712
        elif timeofday == 'night':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == True)  # noqa: E712
        else:
            pass


        # set order
        videos_query = videos_query.order_by(
            IndiAllSkyDbVideoTable.dayDate.desc(),
            IndiAllSkyDbVideoTable.night.desc(),
        )


        videos_data = []
        for v in videos_query:
            try:
                uri = v.getUri()
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            entry = {
                'url'        : str(uri),
                'dayDate'    : v.dayDate.strftime('%B %d, %Y'),
                'night'      : v.night,
            }
            videos_data.append(entry)

        # cannot query the DB from inside the DB query
        for entry in videos_data:
            dayDate = datetime.strptime(entry['dayDate'], '%B %d, %Y').date()

            # Querying the oldest due to a bug where regeneated files are added with the wrong dayDate
            # fix is inbound

            keogram_entry = IndiAllSkyDbKeogramTable.query\
                .filter(IndiAllSkyDbKeogramTable.dayDate == dayDate)\
                .filter(IndiAllSkyDbKeogramTable.night == entry['night'])\
                .order_by(IndiAllSkyDbKeogramTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if keogram_entry:
                try:
                    keogram_url = keogram_entry.getUri()
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    keogram_url = None
            else:
                keogram_url = None


            startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                .filter(IndiAllSkyDbStarTrailsTable.dayDate == dayDate)\
                .filter(IndiAllSkyDbStarTrailsTable.night == entry['night'])\
                .order_by(IndiAllSkyDbStarTrailsTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if startrail_entry:
                try:
                    startrail_url = startrail_entry.getUri()
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    startrail_url = None
            else:
                startrail_url = None


            entry['keogram']    = str(keogram_url)
            entry['startrail']  = str(startrail_url)


        return videos_data



class IndiAllskyVideoViewerPreload(IndiAllskyVideoViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyVideoViewerPreload, self).__init__(*args, **kwargs)

        last_video = IndiAllSkyDbVideoTable.query\
            .order_by(IndiAllSkyDbVideoTable.dayDate.desc())\
            .first()

        if not last_video:
            app.logger.warning('No timelapses found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)

            return


        year = last_video.dayDate.strftime('%Y')


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = self.getMonths(year)

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
        ('generate', 'Generate'),
        ('delete', 'Delete'),
    )

    ACTION_SELECT      = SelectField('Action', choices=ACTION_SELECT_choices, validators=[DataRequired()])
    DAY_SELECT         = SelectField('Day', choices=[], validators=[DataRequired()])


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
            day_list.append(entry.day)


        day_choices = list()
        for d in day_list:
            day_date = datetime.strptime(d, '%Y-%m-%d').date()
            day_str = day_date.strftime('%Y-%m-%d')

            # syntastic does not like booleans in queries directly
            true = True
            false = False

            day_night_str = '{0:s} Night'.format(day_str)
            day_day_str = '{0:s} Day'.format(day_str)

            video_entry_night = IndiAllSkyDbVideoTable.query\
                .filter(IndiAllSkyDbVideoTable.dayDate == day_date)\
                .filter(IndiAllSkyDbVideoTable.night == true)\
                .first()

            if video_entry_night:
                day_night_str = '{0:s} [T]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            video_entry_day = IndiAllSkyDbVideoTable.query\
                .filter(IndiAllSkyDbVideoTable.dayDate == day_date)\
                .filter(IndiAllSkyDbVideoTable.night == false)\
                .first()

            if video_entry_day:
                day_day_str = '{0:s} [T]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            keogram_entry_night = IndiAllSkyDbKeogramTable.query\
                .filter(IndiAllSkyDbKeogramTable.dayDate == day_date)\
                .filter(IndiAllSkyDbKeogramTable.night == true)\
                .first()

            if keogram_entry_night:
                day_night_str = '{0:s} [K]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            keogram_entry_day = IndiAllSkyDbKeogramTable.query\
                .filter(IndiAllSkyDbKeogramTable.dayDate == day_date)\
                .filter(IndiAllSkyDbKeogramTable.night == false)\
                .first()

            if keogram_entry_day:
                day_day_str = '{0:s} [K]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            startrail_entry_night = IndiAllSkyDbStarTrailsTable.query\
                .filter(IndiAllSkyDbStarTrailsTable.dayDate == day_date)\
                .filter(IndiAllSkyDbStarTrailsTable.night == true)\
                .first()

            if startrail_entry_night:
                day_night_str = '{0:s} [S]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            entry_night = ('{0:s}_night'.format(day_str), day_night_str)
            day_choices.append(entry_night)

            entry_day = ('{0:s}_day'.format(day_str), day_day_str)
            day_choices.append(entry_day)

        return day_choices



class IndiAllskySystemInfoForm(FlaskForm):
    # fake form to send commands to web application

    SERVICE_HIDDEN      = HiddenField('service_hidden', validators=[DataRequired()])
    COMMAND_HIDDEN      = HiddenField('command_hidden', validators=[DataRequired()])



class IndiAllskyHistoryForm(FlaskForm):
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
        ('25', 'Fast'),
        ('50', 'Medium'),
        ('75', 'Slow'),
        ('150', 'Very Slow'),
    )

    HISTORY_SELECT       = SelectField('History', choices=HISTORY_SELECT_choices, default=HISTORY_SELECT_choices[0][0], validators=[])
    FRAMEDELAY_SELECT    = SelectField('Speed', choices=FRAMEDELAY_SELECT_choices, default=FRAMEDELAY_SELECT_choices[2][0], validators=[])
    ROCK_CHECKBOX        = BooleanField('Rock', default=False)



class IndiAllskySetDateTimeForm(FlaskForm):

    NEW_DATETIME = DateTimeLocalField('New Datetime', render_kw={'step' : '1'}, format='%Y-%m-%dT%H:%M:%S', validators=[DataRequired()])



class IndiAllskyFocusForm(FlaskForm):
    ZOOM_SELECT_choices = (
        (2, 'Off'),
        (3, 'Low'),
        (5, 'Medium'),
        (8, 'High'),
        (12, 'Extreme'),
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

