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

class IndiAllskyConfigForm(FlaskForm):
    CAMERA_INTERFACE_choices = {
        'INDI' : (
            ('indi', 'INDI - ZWO, PlayerOne, SVBony, Altair, ToupTek, etc'),
        ),
        'libcamera' : (
            ('libcamera_imx477', 'libcamera IMX477 - Raspberry Pi HQ Camera'),
            ('libcamera_imx378', 'libcamera IMX378'),
            ('libcamera_imx708', 'libcamera IMX708 - Camera Module 3'),
            ('libcamera_imx519', 'libcamera IMX519'),
            ('libcamera_imx462', 'libcamera IMX462'),
            ('libcamera_imx327', 'libcamera IMX327'),
            ('libcamera_imx678', 'libcamera IMX678 - Darksee'),
            ('libcamera_imx335', 'libcamera IMX335'),
            ('libcamera_imx500_ai', 'libcamera IMX500 - AI Camera'),
            ('libcamera_imx283', 'libcamera IMX283 - Klarity/OneInchEye'),
            ('libcamera_imx296_gs', 'libcamera IMX296 - Global Shutter - Mono'),
            ('libcamera_imx296_gs_color', 'libcamera IMX296 - Global Shutter - Color'),
            ('libcamera_imx290', 'libcamera IMX290'),
            ('libcamera_imx298', 'libcamera IMX298'),
            ('libcamera_imx219', 'libcamera IMX219 - Camera Module 2'),
            ('libcamera_ov5647', 'libcamera OV5647'),
            ('libcamera_64mp_hawkeye', 'libcamera 64mp HawkEye (IMX682)'),
            ('libcamera_64mp_owlsight', 'libcamera 64mp OwlSight (OV64A40)'),
        ),
        'Network Web Cameras' : (
            ('pycurl_camera', 'pyCurl Camera'),
        ),
        'Special Function' : (
            ('indi_accumulator', 'INDI Accumulator'),
            ('indi_passive', 'INDI (Passive)'),
            ('mqtt_imx477', 'MQTT IMX477 - Raspberry Pi HQ Camera'),
            ('mqtt_imx378', 'MQTT IMX378'),
            ('mqtt_imx708', 'MQTT IMX708 - Camera Module 3'),
            ('mqtt_64mp_owlsight', 'MQTT 64MP OwlSight (OV64A40)'),
        ),
        'Test Cameras' : (
            ('test_rotating_stars', 'Test Camera - Rotating Stars'),
            ('test_bubbles', 'Test Camera - Bubbles'),
        ),
    }

    CCD_CONFIG__EXPOSURE_CLASSNAME_choices = {
        'Basic' : (
            ('exposure_basic', 'Fixed Gains [Day, Night, & Moon Mode]'),
        ),
        'Exposure Priority - Auto-Gain' : (
            ('exposure_autogain_exp_prio_db_1_10', Markup('<sup>1</sup>&frasl;<sub>10</sub> dB - ZWO ASI, PlayerOne [Gain: 0-300]')),
            ('exposure_autogain_exp_prio_iso_1_100', Markup('<sup>1</sup>&frasl;<sub>100</sub> ISO - libcamera [Gain: 1-22.26]')),
            ('exposure_autogain_exp_prio_iso', 'Native ISO - ToupTek, Altair, Omegon, Ogma [Gain: 100-10000]'),
            ('exposure_autogain_exp_prio_db', 'Native dB - QHY [Gain: 0-30]'),
        ),
        'Legacy' : (
            ('exposure_legacy_autogain', '[Legacy] - Auto-Gain'),
        ),
    }

    CCD_CONFIG__AUTO_GAIN_LEVELS_choices = (
        ('12', '12'),
        ('11', '11'),
        ('10', '10'),
        ('9', '9'),
        ('8', '8'),
        ('7', '7'),
        ('6', '6'),
        ('5', '5'),
        ('4', '4'),
    )

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

    IMAGE_SAVE_FITS_PERIOD_choices = (
        ('0', 'Every Image'),
        ('30', '30 seconds'),
        ('60', '1 minute'),
        ('120', '2 minutes'),
        ('180', '3 minutes'),
        ('300', '5 minutes'),
        ('600', '10 minutes'),
        ('1800', '30 minutes'),
        ('3600', '1 hour'),
        ('7200', '2 hours'),
        ('14400', '4 hours'),
        ('21600', '6 hours'),
        ('43200', '12 hours'),
    )

    CFA_PATTERN_choices = (
        ('', 'Auto Detect'),
        ('RGGB', 'RGGB'),
        ('GRBG', 'GRBG'),
        ('BGGR', 'BGGR'),
        ('GBRG', 'GBRG'),
    )

    IMAGE_COLORMAP_choices = (
        ('', 'None'),
        ('COLORMAP_JET', 'Jet'),
        ('COLORMAP_TURBO', 'Turbo'),
        ('COLORMAP_BONE', 'Bone'),
        ('COLORMAP_RAINBOW', 'Rainbow'),
        ('COLORMAP_SPRING', 'Spring'),
        ('COLORMAP_AUTUMN', 'Autumn'),
        ('COLORMAP_HOT', 'Hot'),
        ('COLORMAP_MAGMA', 'Magma'),
        ('COLORMAP_INFERNO', 'Inferno'),
        ('COLORMAP_CIVIDIS', 'Cividis'),
        ('COLORMAP_PARULA', 'Parula'),
        ('COLORMAP_OCEAN', 'Ocean'),
        ('COLORMAP_PINK', 'Pink'),
        ('COLORMAP_DEEPGREEN', 'Deep Green'),
    )

    SCNR_ALGORITHM_choices = (
        ('', 'Disabled'),
        ('average_neutral', 'Average Neutral'),
        ('maximum_neutral', 'Maximum Neutral'),
        ('green_mtf', 'Midtone Transfer Function'),
    )

    IMAGE_DENOISE_choices = (
        ('', 'Disabled'),
        ('gaussian_blur', 'Gaussian Blur Filter — smooths uniformly'),
        ('median_blur', 'Median Filter — removes salt-and-pepper noise'),
        ('bilateral', 'Bilateral Filter— smooths sky background'),
        ('wavelet', 'Wavelet Filter— frequency-domain, best quality (slow)'),
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
        ('h264_nvenc', 'h264 (NVENC) - Nvidia GPU Encoder'),
        ('h264_vaapi', 'h264 (VAAPI) - AMD GPU VCE Encoder'),
        ('h264_qsv', 'h264 (QSV) - Intel Quick Sync Video'),
        ('h264_omx', 'h264 (OMX) - Raspberry Pi (32-bit only)'),
        ('libx265', 'x265 hevc - DO NOT USE'),
        ('hevc_v4l2m2m', 'h265 hevc (v4l2m2m) - DO NOT USE'),
    )


    TIMELAPSE__PRE_PROCESSOR_choices = (
        ('standard', 'Standard - No Processing'),
        ('wrap_keogram', 'Wrap Keogram Around Image Circle [Keolapse]'),
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
        ('boto3_generic', 'Generic (boto3)'),
        ('libcloud_s3', 'Apache Libcloud (AWS)'),
        ('gcp_storage', 'Google Cloud Storage'),
        ('oci_storage', 'Oracle OCI Storage'),
    )

    MQTTPUBLISH__TRANSPORT_choices = (
        ('tcp', 'tcp'),
        ('websockets', 'websockets'),
    )

    MQTTPUBLISH__PROTOCOL_choices = (
        ('MQTTv5', 'v5.0'),
        ('MQTTv311', 'v3.1.1'),
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

    CIRCULAR_DISPLAY__RESOLUTION_choices = (
        ('800', '800x800'),
        ('720', '720x720'),
        ('1080', '1080x1080'),
    )

    IMAGE_OVERLAY__IMAGE_FILE_TYPE_choices = (
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
        ('mode3_adaptive_mtf', 'Adaptive Midtone Transfer Function Transformation'),
    )


    FOCUSER__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_focuser_28byj_64', '28BYJ-48 Stepper (1/64) ULN2003 - GPIO (4 pins)'),
        ('blinka_focuser_28byj_16', '28BYJ-48 Stepper (1/16) ULN2003 - GPIO (4 pins)'),
        ('blinka_focuser_a4988_nema17_full', 'A4988 NEMA17 Stepper - Full Step - GPIO (2 pins)'),
        ('blinka_focuser_a4988_nema17_half', 'A4988 NEMA17 Stepper - Half Step - GPIO (3 pins)'),
        ('motorkit_focuser_single_step', 'Adafruit Motor Shield [i2c]'),
        ('serial_focuser_28byj_64', '28BYJ-48 Stepper (1/64) ULN2003 [Serial Port] (BETA)'),
        ('focuser_simulator', 'Focuser Simulator'),
    )

    DEW_HEATER__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_dew_heater_standard', 'Dew Heater - Standard'),
        ('blinka_dew_heater_pwm', 'Dew Heater - PWM'),
        ('rpigpio_dew_heater_software_pwm', 'Dew Heater - Software PWM [RPi.GPIO] (BETA)'),
        ('gpiozero_dew_heater_software_pwm', 'Dew Heater - Software PWM [gpiozero] (BETA)'),
        ('motorkit_dew_heater_pwm', 'Dew Heater - PWM - Adafruit Motor Shield [i2c]'),
        ('dew_heater_dockerpi_4channel_relay', 'Dew Heater - DockerPi 4 Channel Relay [i2c] (BETA)'),
        ('mqtt_dew_heater_standard', 'Dew Heater - MQTT Standard'),
        ('mqtt_dew_heater_pwm', 'Dew Heater - MQTT PWM'),
        ('serial_dew_heater_pwm', 'Dew Heater - PWM [Serial Port] (BETA)'),
    )

    FAN__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_fan_standard', 'Fan - Standard'),
        ('blinka_fan_pwm', 'Fan - PWM'),
        ('rpigpio_fan_software_pwm', 'Fan - Software PWM [RPi.GPIO] (BETA)'),
        ('gpiozero_fan_software_pwm', 'Fan - Software PWM [gpiozero] (BETA)'),
        ('motorkit_fan_pwm', 'Fan - PWM - Adafruit Motor Shield [i2c]'),
        ('fan_dockerpi_4channel_relay', 'Fan - DockerPi 4 Channel Relay [i2c] (BETA)'),
        ('mqtt_fan_standard', 'Fan - MQTT Standard'),
        ('mqtt_fan_pwm', 'Fan - MQTT PWM'),
        ('serial_fan_pwm', 'Fan - PWM [Serial Port] (BETA)'),
    )

    GENERIC_GPIO__CLASSNAME_choices = (
        ('', 'None'),
        ('blinka_gpio_standard', 'GPIO - Standard'),
        ('gpio_dockerpi_4channel_relay', 'GPIO - DockerPi 4 Channel Relay (BETA)'),
    )

    MANUAL_GPIO__CLASSNAME_choices = (
        ('', 'None'),
        ('rpigpio_gpio_rpigpio', 'Raspberry Pi - [RPi.GPIO]'),
    )

    TEMP_SENSOR__CLASSNAME_choices = {
        'Disabled' : (
            ('', 'None'),
        ),
        'API Services' : (
            ('temp_api_openweathermap', 'OpenWeather API (10 slots)'),
            ('temp_api_weatherunderground', 'Weather Underground API (9 slots)'),
            ('temp_api_astrospheric', 'Astrospheric API (6 slots)'),
            ('temp_api_ambientweather', 'AmbientWeather API (10 slots)'),
            ('temp_api_ecowitt', 'Ecowitt API (10)'),
        ),
        'Temperature Sensors' : (
            ('kernel_temp_sensor_ds18x20_w1', 'DS18x20 - Temp (1 slot)'),
            ('blinka_temp_sensor_dht22', 'DHT22/AM2302 - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_dht21', 'DHT21/AM2301 - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_dht11', 'DHT11 - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_bmp180_i2c', 'BMP180 i2c - Temp/Pres (2 slots)'),
            ('blinka_temp_sensor_bmp280_i2c', 'BMP280 i2c - Temp/Pres (2 slots)'),
            ('blinka_temp_sensor_bmp280_spi', 'BMP280 SPI - Temp/Pres (2 slots)'),
            ('blinka_temp_sensor_bme280_i2c', 'BME280 i2c - Temp/RH/Pres/DP (4 slots)'),
            ('blinka_temp_sensor_bme280_spi', 'BME280 SPI - Temp/RH/Pres/DP (4 slots)'),
            ('blinka_temp_sensor_bme680_i2c', 'BME680 i2c - Temp/RH/Pres/Gas/DP (5 slots)'),
            ('blinka_temp_sensor_bme680_spi', 'BME680 SPI - Temp/RH/Pres/Gas/DP (5 slots)'),
            ('blinka_temp_sensor_bmp3xx_i2c', 'BMP3xx i2c - Temp/Pres (2 slots)'),
            ('blinka_temp_sensor_bmp3xx_spi', 'BMP3xx SPI - Temp/Pres (2 slots)'),
            ('blinka_temp_sensor_si7021_i2c', 'Si7021 i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_sht3x_i2c', 'SHT3x i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_sht4x_i2c', 'SHT40/41/45 i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_htu21d_i2c', 'HTU21D i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_htu31d_i2c', 'HTU31D i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_ahtx0_i2c', 'AHT10/20 i2c - Temp/RH/DP (3 slots)'),
            ('blinka_temp_sensor_scd30_i2c', 'SCD-30 i2c - Temp/RH/CO2/DP (4 slots)'),
            ('blinka_temp_sensor_scd4x_i2c', 'SCD-4x i2c - Temp/RH/CO2/DP (4 slots)'),
            ('blinka_temp_sensor_hdc302x_i2c', 'HDC302x i2c - Temp/RH/DP (3 slots)'),
            ('cpads_temp_sensor_tmp36_ads1015_i2c', 'TMP36 ADS1015 i2c - Temp (1 slot)'),
            ('cpads_temp_sensor_tmp36_ads1115_i2c', 'TMP36 ADS1115 i2c - Temp (1 slot)'),
            ('cpads_temp_sensor_lm35_ads1015_i2c', 'LM35 ADS1015 i2c - Temp (1 slot)'),
            ('cpads_temp_sensor_lm35_ads1115_i2c', 'LM35 ADS1115 i2c - Temp (1 slot)'),
            ('blinka_temp_sensor_mlx90614_i2c', 'MLX90614 i2c - Temp/SkyTemp (2 slots)'),
            ('blinka_temp_sensor_mlx90615_i2c', 'MLX90615 i2c - Temp/SkyTemp (2 slots)'),
            ('blinka_temp_sensor_mlx90640_i2c', 'MLX90640 i2c - SkyTemp (1 slot)'),
        ),
        'Light/Lux Sensors' : (
            ('blinka_light_sensor_tsl2561_i2c', 'TSL2561 i2c - Lux/Full/IR/SQM/Mag (5 slots)'),
            ('blinka_light_sensor_tsl2591_i2c', 'TSL2591 i2c - Lux/Vis/IR/Full/SQM/Mag (6 slots)'),
            ('blinka_light_sensor_veml7700_i2c', 'VEML7700 i2c - Lux/Light/White/SQM/Mag (5 slots)'),
            ('blinka_light_sensor_bh1750_i2c', 'BH1750 i2c - Lux/SQM/Mag (3 slots)'),
            ('blinka_light_sensor_si1145_i2c', 'SI1145 i2c - Vis/IR/UV/SQM/Mag (5 slots)'),
            ('blinka_light_sensor_ltr390_i2c', 'LTR390 i2c - UV/Vis/UVI/Lux/SQM/Mag (6 slots)'),
        ),
        'Magnetometer/Gauss Sensors' : (
            ('qwiic_mag_sensor_mmc5983ma_i2c', 'MMC5983MA i2c - X/Y/Z/Temp (4 slots)'),
        ),
        'IMU Sensors' : (
            ('blinka_imu_sensor_icm20x_i2c', 'ICM20X i2c - Mag X/Y/Z (3 slots)'),
            ('blinka_imu_sensor_mpu6050_i2c', 'MPU6050 i2c - Temp (1 slot)'),
        ),
        'VOC/Air Quality Sensors' : (
            ('blinka_voc_sensor_sgp40_i2c', 'SGP40 i2c - Gas (1 slot)'),
        ),
        'Current Sensors' : (
            ('blinka_ups_hat_waveshare_e_mcu_i2c', 'Waveshare UPS HAT (E) MCU @0x2D - Battery/VBUS/Cells (12 slots)'),
            ('blinka_current_sensor_ina219_i2c', 'INA219 i2c - V/A/W (3 slots)'),
            ('blinka_current_sensor_ina228_i2c', 'INA228 i2c - V/A/W/Temp (4 slots)'),
            ('blinka_current_sensor_ina260_i2c', 'INA260 i2c - V/A/W (3 slots)'),
            ('blinka_current_sensor_ina23x_i2c', 'INA23x i2c - V/A/W/Temp (4 slots)'),
            ('blinka_current_sensor_ina3221_i2c', 'INA3221 i2c - 3 Channel V/A/W (9 slots)'),
        ),
        'Lightning Sensors' : (
            ('blinka_sparkfun_lightning_sensor_as3935_spi', 'AS3935 SPI - (6 slots) [BETA]'),
            ('blinka_sparkfun_lightning_sensor_as3935_i2c', 'AS3935 i2c - (6 slots) [BETA]'),
        ),
        'Rain Sensors' : (
            ('blinka_rain_sensor_fc37', 'FC-37 Rain Sensor - digital (1 slot)'),
        ),
        'Remote' : (
            ('mqtt_broker_sensor', 'MQTT Broker Sensor - (10 slots)'),
        ),
        'Testing' : (
            ('sensor_data_generator', 'Test Data Generator - (7 slots)'),
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
        ('sensor_user_30', 'User Slot 30'),
        ('sensor_user_31', 'User Slot 31'),
        ('sensor_user_32', 'User Slot 32'),
        ('sensor_user_33', 'User Slot 33'),
        ('sensor_user_34', 'User Slot 34'),
        ('sensor_user_35', 'User Slot 35'),
        ('sensor_user_36', 'User Slot 36'),
        ('sensor_user_37', 'User Slot 37'),
        ('sensor_user_38', 'User Slot 38'),
        ('sensor_user_39', 'User Slot 39'),
        ('sensor_user_40', 'User Slot 40'),
        ('sensor_user_41', 'User Slot 41'),
        ('sensor_user_42', 'User Slot 42'),
        ('sensor_user_43', 'User Slot 43'),
        ('sensor_user_44', 'User Slot 44'),
        ('sensor_user_45', 'User Slot 45'),
        ('sensor_user_46', 'User Slot 46'),
        ('sensor_user_47', 'User Slot 47'),
        ('sensor_user_48', 'User Slot 48'),
        ('sensor_user_49', 'User Slot 49'),
        ('sensor_user_50', 'User Slot 50'),
        ('sensor_user_51', 'User Slot 51'),
        ('sensor_user_52', 'User Slot 52'),
        ('sensor_user_53', 'User Slot 53'),
        ('sensor_user_54', 'User Slot 54'),
        ('sensor_user_55', 'User Slot 55'),
        ('sensor_user_56', 'User Slot 56'),
        ('sensor_user_57', 'User Slot 57'),
        ('sensor_user_58', 'User Slot 58'),
        ('sensor_user_59', 'User Slot 59'),
    )


    # SENSOR_SLOT_choices will be merged with this var
    CUSTOM_CHART_choices = {
        'Aurora' : (
            ['kpindex', 'Planetary K-Index (kpindex)'],
            ['ovation_max', 'Aurora Chance'],
            ['aurora_mag_bt', 'Solar Wind Bt (nT)'],
            ['aurora_mag_gsm_bz', 'Solar Wind Bz'],
            ['aurora_plasma_density', 'Solar Wind Plasma Density [1/cm³]'],
            ['aurora_plasma_speed', 'Solar Wind Plasma Speed [km/s]'],
            ['aurora_plasma_temp', 'PSolar Wind lasma Temperature [K]'],
            ['aurora_n_hemi_gw', 'Hemispheric Power - Northern [GW]'],
            ['aurora_s_hemi_gw', 'Hemispheric Power - Southern [GW]'],
        ),
        'SQM' : (
            ['camera_sqm_raw_mag', 'Camera SQM - Raw Magnitude'],
        ),
    }


    SENSOR_SLOT_choices = {
        'User Sensors' : (
            ['sensor_user_0', '(0) User Slot - Camera Temp'],  # mutable
            ['sensor_user_1', '(1) User Slot - Dew Heater Level'],
            ['sensor_user_2', '(2) User Slot - Dew Point'],
            ['sensor_user_3', '(3) User Slot - Frost Point'],
            ['sensor_user_4', '(4) User Slot - Fan Level'],
            ['sensor_user_5', '(5) User Slot - Heat Index'],
            ['sensor_user_6', '(6) User Slot - Wind Dir (Degrees)'],
            ['sensor_user_7', '(7) User Slot - Sensor SQM Magnitude (mag/arcsec²)'],
            ['sensor_user_8', '(8) User Slot - Camera SQM Magnitude (mag/arcsec²)'],
            ['sensor_user_9', '(9) User Slot - Camera SQM ADU'],
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
            ['sensor_user_30', 'User Slot 30'],
            ['sensor_user_31', 'User Slot 31'],
            ['sensor_user_32', 'User Slot 32'],
            ['sensor_user_33', 'User Slot 33'],
            ['sensor_user_34', 'User Slot 34'],
            ['sensor_user_35', 'User Slot 35'],
            ['sensor_user_36', 'User Slot 36'],
            ['sensor_user_37', 'User Slot 37'],
            ['sensor_user_38', 'User Slot 38'],
            ['sensor_user_39', 'User Slot 39'],
            ['sensor_user_40', 'User Slot 40'],
            ['sensor_user_41', 'User Slot 41'],
            ['sensor_user_42', 'User Slot 42'],
            ['sensor_user_43', 'User Slot 43'],
            ['sensor_user_44', 'User Slot 44'],
            ['sensor_user_45', 'User Slot 45'],
            ['sensor_user_46', 'User Slot 46'],
            ['sensor_user_47', 'User Slot 47'],
            ['sensor_user_48', 'User Slot 48'],
            ['sensor_user_49', 'User Slot 49'],
            ['sensor_user_50', 'User Slot 50'],
            ['sensor_user_51', 'User Slot 51'],
            ['sensor_user_52', 'User Slot 52'],
            ['sensor_user_53', 'User Slot 53'],
            ['sensor_user_54', 'User Slot 54'],
            ['sensor_user_55', 'User Slot 55'],
            ['sensor_user_56', 'User Slot 56'],
            ['sensor_user_57', 'User Slot 57'],
            ['sensor_user_58', 'User Slot 58'],
            ['sensor_user_59', 'User Slot 59'],
            ['sensor_user_100', '(100) User Slot - Rain Value'],
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
            ['sensor_temp_30', 'System Temp 30'],
            ['sensor_temp_31', 'System Temp 31'],
            ['sensor_temp_32', 'System Temp 32'],
            ['sensor_temp_33', 'System Temp 33'],
            ['sensor_temp_34', 'System Temp 34'],
            ['sensor_temp_35', 'System Temp 35'],
            ['sensor_temp_36', 'System Temp 36'],
            ['sensor_temp_37', 'System Temp 37'],
            ['sensor_temp_38', 'System Temp 38'],
            ['sensor_temp_39', 'System Temp 39'],
            ['sensor_temp_40', 'System Temp 40'],
            ['sensor_temp_41', 'System Temp 41'],
            ['sensor_temp_42', 'System Temp 42'],
            ['sensor_temp_43', 'System Temp 43'],
            ['sensor_temp_44', 'System Temp 44'],
            ['sensor_temp_45', 'System Temp 45'],
            ['sensor_temp_46', 'System Temp 46'],
            ['sensor_temp_47', 'System Temp 47'],
            ['sensor_temp_48', 'System Temp 48'],
            ['sensor_temp_49', 'System Temp 49'],
            ['sensor_temp_50', 'System Temp 50'],
            ['sensor_temp_51', 'System Temp 51'],
            ['sensor_temp_52', 'System Temp 52'],
            ['sensor_temp_53', 'System Temp 53'],
            ['sensor_temp_54', 'System Temp 54'],
            ['sensor_temp_55', 'System Temp 55'],
            ['sensor_temp_56', 'System Temp 56'],
            ['sensor_temp_57', 'System Temp 57'],
            ['sensor_temp_58', 'System Temp 58'],
            ['sensor_temp_59', 'System Temp 59'],
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

    DETECT_STARS_METHOD_choices = (
        ('template', 'Template Match'),
        ('sep', 'SEP (Source Extractor)'),
    )


    ENCRYPT_PASSWORDS                = BooleanField('Encrypt Passwords')
    CAMERA_INTERFACE                 = SelectField('Camera Interface', choices=CAMERA_INTERFACE_choices, validators=[DataRequired(), CAMERA_INTERFACE_validator])
    INDI_SERVER                      = StringField('INDI Server', validators=[DataRequired(), INDI_SERVER_validator])
    INDI_PORT                        = IntegerField('INDI port', validators=[DataRequired(), INDI_PORT_validator])
    INDI_CAMERA_NAME                 = StringField('INDI Camera Name', validators=[INDI_CAMERA_NAME_validator])
    WEBSITE__TITLE                   = StringField('Website Title', validators=[WEBSITE__TITLE_validator])
    OWNER                            = StringField('Owner', validators=[OWNER_validator])
    LENS_NAME                        = StringField('Lens Name', validators=[LENS_NAME_validator])
    LENS_FOCAL_LENGTH                = FloatField('Focal Length', validators=[LENS_FOCAL_LENGTH_validator])
    LENS_FOCAL_RATIO                 = FloatField('Focal Ratio', validators=[LENS_FOCAL_RATIO_validator])
    LENS_IMAGE_CIRCLE                = IntegerField('Image Circle', validators=[LENS_IMAGE_CIRCLE_validator])
    LENS_OFFSET_X                    = IntegerField('Image Circle X Offset', validators=[LENS_OFFSET_validator])
    LENS_OFFSET_Y                    = IntegerField('Image Circle Y Offset', validators=[LENS_OFFSET_validator])
    LENS_ALTITUDE                    = FloatField('Altitude', validators=[LENS_ALTITUDE_validator])
    LENS_AZIMUTH                     = FloatField('Azimuth', validators=[LENS_AZIMUTH_validator])
    CCD_CONFIG__NIGHT__GAIN          = FloatField('Night Gain', validators=[CCD_GAIN_validator])
    CCD_CONFIG__NIGHT__BINNING       = IntegerField('Night Bin Mode', validators=[DataRequired(), CCD_BINNING_validator])
    CCD_CONFIG__MOONMODE__GAIN       = FloatField('Moon Mode Gain', validators=[CCD_GAIN_validator])
    CCD_CONFIG__MOONMODE__BINNING    = IntegerField('Moon Mode Bin Mode', validators=[DataRequired(), CCD_BINNING_validator])
    CCD_CONFIG__DAY__GAIN            = FloatField('Daytime Gain', validators=[CCD_GAIN_validator])
    CCD_CONFIG__DAY__BINNING         = IntegerField('Daytime Bin Mode', validators=[DataRequired(), CCD_BINNING_validator])
    CCD_CONFIG__EXPOSURE_CLASSNAME   = SelectField('Exposure Mode', choices=CCD_CONFIG__EXPOSURE_CLASSNAME_choices, validators=[CCD_CONFIG__EXPOSURE_CLASSNAME_validator])
    CCD_CONFIG__AUTO_GAIN_LEVELS     = SelectField('Auto-Gain Levels [Legacy]', choices=CCD_CONFIG__AUTO_GAIN_LEVELS_choices, validators=[CCD_CONFIG__AUTO_GAIN_LEVELS_validator])
    CCD_EXPOSURE_MAX                 = FloatField('Max Exposure', validators=[DataRequired(), CCD_EXPOSURE_validator])
    CCD_EXPOSURE_DEF                 = FloatField('Default Exposure', validators=[CCD_EXPOSURE_validator])
    CCD_EXPOSURE_MIN                 = FloatField('Min Exposure (Night)', validators=[CCD_EXPOSURE_validator])
    CCD_EXPOSURE_MIN_DAY             = FloatField('Min Exposure (Day)', validators=[CCD_EXPOSURE_validator])
    CCD_EXPOSURE_TIMEOUT             = IntegerField('Exposure Timeout', validators=[CCD_EXPOSURE_TIMEOUT_validator])
    CCD_BIT_DEPTH                    = SelectField('Camera Bit Depth', choices=CCD_BIT_DEPTH_choices, validators=[CCD_BIT_DEPTH_validator])
    EXPOSURE_PERIOD                  = FloatField('Exposure Period (Night)', validators=[DataRequired(), EXPOSURE_PERIOD_validator])
    EXPOSURE_PERIOD_DAY              = FloatField('Exposure Period (Day)', validators=[DataRequired(), EXPOSURE_PERIOD_DAY_validator])
    CAMERA_SQM__ENABLE               = BooleanField('Enable Camera SQM')
    CAMERA_SQM__ENABLE_DAY           = BooleanField('Enable Daytime SQM')
    CAMERA_SQM__EXPOSURE             = FloatField('Camera SQM Exposure', validators=[DataRequired(), CAMERA_SQM__EXPOSURE_validator])
    CAMERA_SQM__GAIN                 = FloatField('Camera SQM Gain', validators=[CCD_GAIN_validator])
    CAMERA_SQM__BINNING              = IntegerField('Camera SQM Binning', validators=[CCD_BINNING_validator])
    CAMERA_SQM__EXPOSURE_PERIOD      = IntegerField('SQM Exposure Period', validators=[DataRequired(), CAMERA_SQM__EXPOSURE_PERIOD_validator])
    CAMERA_SQM__MAGNITUDE_OFFSET     = FloatField('Magnitude Offset', validators=[SQM_MAGNITUDE_OFFSET_validator])
    FOCUS_MODE                       = BooleanField('Focus Mode')
    FOCUS_DELAY                      = FloatField('Focus Delay', validators=[DataRequired(), FOCUS_DELAY_validator])
    CFA_PATTERN                      = SelectField('Bayer Pattern', choices=CFA_PATTERN_choices, validators=[CFA_PATTERN_validator])
    USE_NIGHT_COLOR                  = BooleanField('Use Night Color Settings')
    SCNR_ALGORITHM                   = SelectField('SCNR (Night)', choices=SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    SCNR_ALGORITHM_DAY               = SelectField('SCNR (Day)', choices=SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    SCNR_MTF_MIDTONES                = FloatField('SCNR MTF Midtones (Night)', validators=[SCNR_MTF_MIDTONES_validator])
    SCNR_MTF_MIDTONES_DAY            = FloatField('SCNR MTF Midtones (Day)', validators=[SCNR_MTF_MIDTONES_validator])
    IMAGE_DENOISE                    = SelectField('Denoise (Night)', choices=IMAGE_DENOISE_choices, validators=[IMAGE_DENOISE_validator])
    IMAGE_DENOISE_DAY                = SelectField('Denoise (Day)', choices=IMAGE_DENOISE_choices, validators=[IMAGE_DENOISE_validator])
    IMAGE_DENOISE_STRENGTH           = IntegerField('Denoise Strength (Night)', validators=[IMAGE_DENOISE_STRENGTH_validator], widget=NumberInput(step=1))
    IMAGE_DENOISE_STRENGTH_DAY       = IntegerField('Denoise Strength (Day)', validators=[IMAGE_DENOISE_STRENGTH_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_COLOR            = IntegerField('Bilateral Sigma Color (Night)', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_COLOR_DAY        = IntegerField('Bilateral Sigma Color (Day)', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_SPACE            = IntegerField('Bilateral Sigma Space (Night)', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_SPACE_DAY        = IntegerField('Bilateral Sigma Space (Day)', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    WBR_FACTOR                       = FloatField('Red Balance Factor (Night)', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBG_FACTOR                       = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBB_FACTOR                       = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBR_FACTOR_DAY                   = FloatField('Red Balance Factor (Day)', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBG_FACTOR_DAY                   = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBB_FACTOR_DAY                   = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    AUTO_WB                          = BooleanField('Auto White Balance (Night)')
    AUTO_WB_DAY                      = BooleanField('Auto White Balance (Day)')
    WBR_MTF_MIDTONES                 = FloatField('Red Balance MTF Midtones (Night)', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBG_MTF_MIDTONES                 = FloatField('Green Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBB_MTF_MIDTONES                 = FloatField('Blue Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBR_MTF_MIDTONES_DAY             = FloatField('Red Balance MTF Midtones (Day)', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBG_MTF_MIDTONES_DAY             = FloatField('Green Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBB_MTF_MIDTONES_DAY             = FloatField('Blue Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    SATURATION_FACTOR                = FloatField('Saturation Factor (Night)', validators=[SATURATION_FACTOR_validator], widget=NumberInput(step=0.1))
    SATURATION_FACTOR_DAY            = FloatField('Saturation Factor (Day)', validators=[SATURATION_FACTOR_validator], widget=NumberInput(step=0.01))
    GAMMA_CORRECTION                 = FloatField('Gamma Correction (Night)', validators=[GAMMA_CORRECTION_validator], widget=NumberInput(step=0.01))
    GAMMA_CORRECTION_DAY             = FloatField('Gamma Correction (Day)', validators=[GAMMA_CORRECTION_validator], widget=NumberInput(step=0.01))
    SHARPEN_AMOUNT                   = FloatField('Sharpen Amount (Night)', validators=[SHARPEN_AMOUNT_validator], widget=NumberInput(step=0.01))
    SHARPEN_AMOUNT_DAY               = FloatField('Sharpen Amount (Day)', validators=[SHARPEN_AMOUNT_validator], widget=NumberInput(step=0.01))
    CCD_COOLING                      = BooleanField('CCD Cooling (Night)')
    CCD_COOLING_DAY                  = BooleanField('CCD Cooling (Day)')
    CCD_TEMP                         = FloatField('Target CCD Temp (Night)', validators=[CCD_TEMP_validator])
    CCD_TEMP_DAY                     = FloatField('Target CCD Temp (Day)', validators=[CCD_TEMP_validator])
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
    DETECT_STARS_METHOD              = SelectField('Star Detection Method', choices=DETECT_STARS_METHOD_choices, validators=[DataRequired()])
    DETECT_STARS_SEP_THOLD           = FloatField('SEP Sigma Threshold', validators=[DataRequired(), DETECT_STARS_SEP_THOLD_validator], widget=NumberInput(step=0.5))
    DETECT_STARS_SEP_MAX_RADIUS      = IntegerField('SEP Max Star Radius', validators=[DataRequired(), DETECT_STARS_SEP_MAX_RADIUS_validator])
    DETECT_METEORS                   = BooleanField('Meteor Detection')
    DETECT_METEORS_THOLD             = IntegerField('Meteor Detection Threshold', validators=[DataRequired(), DETECT_METEORS_THOLD_validator])
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
    TIMELAPSE__PRE_PROCESSOR         = SelectField('Timelapse Processing (Night)', choices=TIMELAPSE__PRE_PROCESSOR_choices, validators=[TIMELAPSE__PRE_PROCESSOR_validator])
    TIMELAPSE__PRE_PROCESSOR_DAY     = SelectField('Timelapse Processing (Day)', choices=TIMELAPSE__PRE_PROCESSOR_choices, validators=[TIMELAPSE__PRE_PROCESSOR_validator])
    TIMELAPSE__IMAGE_CIRCLE          = IntegerField('Image Circle Diameter', validators=[DataRequired(), TIMELAPSE__IMAGE_CIRCLE_validator])
    TIMELAPSE__KEOGRAM_RATIO         = FloatField('Keogram Ratio', validators=[DataRequired(), TIMELAPSE__KEOGRAM_RATIO_validator])
    TIMELAPSE__PRE_SCALE             = IntegerField('Pre-Scale Images', validators=[DataRequired(), TIMELAPSE__PRE_SCALE_validator])
    TIMELAPSE__FFMPEG_REPORT         = BooleanField('Generate FFMPEG debug report')
    TIMELAPSE__USE_NIGHT_CONFIG      = BooleanField('Use Night Settings')
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
    WEBSOCKET_API_KEY                = StringField('WebSocket API Key', validators=[WEBSOCKET_API_KEY_validator])
    WEB_NONLOCAL_IMAGES              = BooleanField('Non-Local Images')
    WEB_LOCAL_IMAGES_ADMIN           = BooleanField('Local Images from Admin Networks')
    IMAGE_STRETCH__CLASSNAME         = SelectField('Stretch Function', choices=IMAGE_STRETCH__CLASSNAME_choices, validators=[IMAGE_STRETCH__CLASSNAME_validator])
    IMAGE_STRETCH__MODE1_GAMMA       = FloatField('StdDev Cutoff - Stretching Gamma', validators=[IMAGE_STRETCH__MODE1_GAMMA_validator])
    IMAGE_STRETCH__MODE1_STDDEVS     = FloatField('StdDev Cutoff - Stretching Std Deviations', validators=[DataRequired(), IMAGE_STRETCH__MODE1_STDDEVS_validator])
    IMAGE_STRETCH__MODE2_SHADOWS     = FloatField('MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE2_SHADOWS_validator])
    IMAGE_STRETCH__MODE2_MIDTONES    = FloatField('MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE2_MIDTONES_validator])
    IMAGE_STRETCH__MODE2_HIGHLIGHTS  = FloatField('MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator])
    IMAGE_STRETCH__MODE3_BLACK_CLIP  = FloatField('Adaptive MTF - Black Clip', validators=[IMAGE_STRETCH__MODE3_BLACK_CLIP_validator])
    IMAGE_STRETCH__MODE3_SHADOWS     = FloatField('Adaptive MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE3_SHADOWS_validator])
    IMAGE_STRETCH__MODE3_MIDTONES    = FloatField('Adaptive MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE3_MIDTONES_validator])
    IMAGE_STRETCH__MODE3_HIGHLIGHTS  = FloatField('Adaptive MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator])
    IMAGE_STRETCH__SPLIT             = BooleanField('Stretching split screen')
    IMAGE_STRETCH__MOONMODE          = BooleanField('Moon Mode Stretching')
    IMAGE_STRETCH__DAYTIME           = BooleanField('Daytime Stretching')
    KEOGRAM_ANGLE                    = FloatField('Keogram Rotation Angle', validators=[KEOGRAM_ANGLE_validator], widget=NumberInput(step=0.1))
    KEOGRAM_H_SCALE                  = IntegerField('Keogram Horizontal Scaling', validators=[DataRequired(), KEOGRAM_H_SCALE_validator])
    KEOGRAM_V_SCALE                  = IntegerField('Keogram Vertical Scaling', validators=[DataRequired(), KEOGRAM_V_SCALE_validator])
    KEOGRAM_CROP_TOP                 = IntegerField('Keogram Crop Top (%)', validators=[KEOGRAM_CROP_TOP_validator])
    KEOGRAM_CROP_BOTTOM              = IntegerField('Keogram Crop Bottom (%)', validators=[KEOGRAM_CROP_BOTTOM_validator])
    KEOGRAM_LABEL                    = BooleanField('Label Keogram')
    LONGTERM_KEOGRAM__ENABLE         = BooleanField('Enable Long Term Keogram')
    LONGTERM_KEOGRAM__OFFSET_X       = IntegerField('X Offset', validators=[LONGTERM_KEOGRAM__OFFSET_X_validator])
    LONGTERM_KEOGRAM__OFFSET_Y       = IntegerField('Y Offset', validators=[LONGTERM_KEOGRAM__OFFSET_Y_validator])
    LONGTERM_KEOGRAM__OPENCV_FONT_SCALE    = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    LONGTERM_KEOGRAM__PIL_FONT_SIZE        = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE = StringField('Month Label Template', validators=[LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator])
    REALTIME_KEOGRAM__MAX_ENTRIES    = IntegerField('Realtime Keogram Max Entries', validators=[REALTIME_KEOGRAM__MAX_ENTRIES_validator])
    REALTIME_KEOGRAM__SAVE_INTERVAL  = IntegerField('Save Interval', validators=[REALTIME_KEOGRAM__SAVE_INTERVAL_validator])
    REALTIME_KEOGRAM__LABEL          = BooleanField('Label Realtime Keogram')
    STARTRAILS_SUN_ALT_THOLD         = FloatField('Star Trails Max Sun Altitude', validators=[DataRequired(), STARTRAILS_SUN_ALT_THOLD_validator])
    STARTRAILS_MOONMODE_THOLD        = BooleanField('Star Trails: Use Camera Moon Mode Thresholds')
    STARTRAILS_MOON_ALT_THOLD        = FloatField('Custom Max Moon Altitude', validators=[DataRequired(), STARTRAILS_MOON_ALT_THOLD_validator])
    STARTRAILS_MOON_PHASE_THOLD      = FloatField('Custom Max Moon Phase', validators=[DataRequired(), STARTRAILS_MOON_PHASE_THOLD_validator])
    STARTRAILS_MAX_ADU               = IntegerField('Star Trails Max ADU', validators=[DataRequired(), STARTRAILS_MAX_ADU_validator])
    STARTRAILS_MASK_THOLD            = IntegerField('Star Trails Mask Threshold ADU', validators=[DataRequired(), STARTRAILS_MASK_THOLD_validator])
    STARTRAILS_PIXEL_THOLD           = FloatField('Star Trails Pixel Threshold', validators=[STARTRAILS_PIXEL_THOLD_validator])
    STARTRAILS_MIN_STARS             = IntegerField('Star Trails Minimum Stars', validators=[STARTRAILS_MIN_STARS_validator])
    STARTRAILS_TIMELAPSE             = BooleanField('Star Trails Timelapse')
    STARTRAILS_TIMELAPSE_MINFRAMES   = IntegerField('Star Trails Timelapse Minimum Frames', validators=[DataRequired(), STARTRAILS_TIMELAPSE_MINFRAMES_validator])
    STARTRAILS_USE_DB_DATA           = BooleanField('Star Trails Use Existing Data')
    STARTRAILS__IMAGE_CIRCLE_MASK_ENABLE    = BooleanField('Enable Image Circle Mask')
    STARTRAILS__IMAGE_CIRCLE_MASK_DIAMETER  = IntegerField('Mask Diameter', validators=[DataRequired(), IMAGE_CIRCLE_MASK__DIAMETER_validator])
    STARTRAILS__IMAGE_CIRCLE_MASK_BLUR      = IntegerField('Mask Blur', validators=[IMAGE_CIRCLE_MASK__BLUR_validator])
    STARTRAILS__IMAGE_CIRCLE_MASK_OPACITY   = IntegerField('Mask Opacity %', validators=[IMAGE_CIRCLE_MASK__OPACITY_validator])
    # Keep the complete model-specific configuration surface together so new
    # controls cannot silently miss the Config load/save wiring below.
    IMAGE_ASI676MC_REPAIR__ENABLE                      = BooleanField('Enable ASI676MC purple-frame handling')
    IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY                = BooleanField('Detect and exclude only')
    IMAGE_ASI676MC_REPAIR__LOG_EVERY_FRAME             = BooleanField('Log every ASI676MC frame')
    IMAGE_ASI676MC_REPAIR__GALLERY_ENABLE              = BooleanField('Show purple-frame status in gallery')
    IMAGE_ASI676MC_REPAIR__SAVE_DIAGNOSTIC_FITS         = BooleanField('Save purple and following normal FITS for calibration')
    IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS          = BooleanField('Also save the preceding normal FITS')
    IMAGE_ASI676MC_REPAIR__PURPLE_RATIO_THRESHOLD      = FloatField('Overall purple-frame threshold', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator], widget=NumberInput(step=0.01))
    IMAGE_ASI676MC_REPAIR__RED_SIDE_RATIO_THRESHOLD    = FloatField('Red-side purple-frame threshold', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator], widget=NumberInput(step=0.01))
    IMAGE_ASI676MC_REPAIR__BLUE_SIDE_RATIO_THRESHOLD   = FloatField('Blue-side purple-frame threshold', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator], widget=NumberInput(step=0.01))
    IMAGE_ASI676MC_REPAIR__SAMPLE_STEP                 = IntegerField('Detection sample step', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator])
    IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD = IntegerField('Clipped-highlight brightness level', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator])
    IMAGE_ASI676MC_REPAIR__GAIN_R                      = FloatField('Red repair gain', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__GAIN_validator], widget=NumberInput(step=0.00001))
    IMAGE_ASI676MC_REPAIR__GAIN_G1                     = FloatField('First green repair gain', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__GAIN_validator], widget=NumberInput(step=0.00001))
    IMAGE_ASI676MC_REPAIR__GAIN_G2                     = FloatField('Second green repair gain', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__GAIN_validator], widget=NumberInput(step=0.00001))
    IMAGE_ASI676MC_REPAIR__GAIN_B                      = FloatField('Blue repair gain', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__GAIN_validator], widget=NumberInput(step=0.00001))
    IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO = FloatField('Highlight correction start', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator], widget=NumberInput(step=0.01))
    IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO   = FloatField('Highlight correction end', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO_validator], widget=NumberInput(step=0.01))
    IMAGE_ASI676MC_REPAIR__CHUNK_ROWS                  = IntegerField('Rows processed at once', validators=[DataRequired(), IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator])
    IMAGE_CALIBRATE_DARK             = BooleanField('Apply Dark Calibration Frames')
    IMAGE_CALIBRATE_BPM              = BooleanField('Apply Bad Pixel Map Frames')
    IMAGE_CALIBRATE_FIX_HOLES        = BooleanField('Fix Calibration Pin Holes')
    IMAGE_CALIBRATE_HOLE_THOLD       = IntegerField('Hole ADU Threshold %', validators=[IMAGE_CALIBRATE_HOLE_THOLD_validator])
    IMAGE_CALIBRATE_MANUAL_OFFSET    = IntegerField('Manual Offset', validators=[IMAGE_CALIBRATE_MANUAL_OFFSET_validator])
    IMAGE_SAVE_FITS_PRE_DARK         = BooleanField('Save FITS Pre-Calibration')
    PRIVACY_MODE                     = BooleanField('Enable Privacy Mode')
    IMAGE_EXIF_PRIVACY               = BooleanField('Enable EXIF Privacy')
    IMAGE_FILE_TYPE                  = SelectField('Image file type', choices=IMAGE_FILE_TYPE_choices, validators=[DataRequired(), IMAGE_FILE_TYPE_validator])
    IMAGE_FILE_COMPRESSION__JPG      = IntegerField('JPEG Quality', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__JPG_validator])
    IMAGE_FILE_COMPRESSION__PNG      = IntegerField('PNG Compression', validators=[DataRequired(), IMAGE_FILE_COMPRESSION__PNG_validator])
    IMAGE_FILE_COMPRESSION__TIF      = StringField('TIFF Compression', render_kw={'readonly' : True, 'disabled' : 'disabled'})
    VARLIB_FOLDER                    = StringField('VARLIB folder', validators=[DataRequired(), VARLIB_FOLDER_validator])
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
    IMAGE_CIRCLE_MASK__OUTLINE       = BooleanField('Mask Outline [DEBUG]')
    IMAGE_CROP_ROI_X1                = IntegerField('Image Crop ROI x1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y1                = IntegerField('Image Crop ROI y1', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_X2                = IntegerField('Image Crop ROI x2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_ROI_Y2                = IntegerField('Image Crop ROI y2', validators=[IMAGE_CROP_ROI_validator])
    IMAGE_CROP_IMAGE_CIRCLE          = BooleanField('Crop to Image Circle')
    IMAGE_COLORMAP                   = SelectField('Apply Colormap', choices=IMAGE_COLORMAP_choices, validators=[IMAGE_COLORMAP_validator])
    IMAGE_QUEUE_MAX                  = IntegerField('Image Queue Maximum', validators=[IMAGE_QUEUE_MAX_validator])
    IMAGE_QUEUE_MIN                  = IntegerField('Image Queue Minimum', validators=[IMAGE_QUEUE_MIN_validator])
    IMAGE_QUEUE_BACKOFF              = FloatField('Image Queue Backoff Multiplier', validators=[IMAGE_QUEUE_BACKOFF_validator])
    IMAGE_SAVE_HOOK_PRE              = StringField('Image Pre-Save Hook', validators=[SCRIPT_validator])
    IMAGE_SAVE_HOOK_POST             = StringField('Image Post-Save Hook', validators=[SCRIPT_validator])
    IMAGE_SAVE_HOOK_TIMEOUT          = IntegerField('Image Save Hook Timeout', validators=[DataRequired(), HOOK_TIMEOUT_validator])
    CAPTURE_HOOK_PRE                 = StringField('Pre-Capture Hook', validators=[SCRIPT_validator])
    CAPTURE_HOOK_TIMEOUT             = IntegerField('Capture Hook Timeout', validators=[DataRequired(), HOOK_TIMEOUT_validator])
    FISH2PANO__ENABLE                = BooleanField('Enable Fisheye to Panoramic')
    FISH2PANO__DIAMETER              = IntegerField('Diameter', validators=[DataRequired(), FISH2PANO__DIAMETER_validator])
    FISH2PANO__OFFSET_X              = IntegerField('X Offset', validators=[FISH2PANO__OFFSET_X_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    FISH2PANO__OFFSET_Y              = IntegerField('Y Offset', validators=[FISH2PANO__OFFSET_Y_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    FISH2PANO__ROTATE_ANGLE          = IntegerField('Rotation Angle', validators=[FISH2PANO__ROTATE_ANGLE_validator])
    FISH2PANO__SCALE                 = FloatField('Scale', validators=[FISH2PANO__SCALE_validator])
    FISH2PANO__MODULUS               = IntegerField('Modulus', validators=[DataRequired(), FISH2PANO__MODULUS_validator])
    FISH2PANO__FLIP_H                = BooleanField('Flip Horizontally')
    FISH2PANO__ENABLE_CARDINAL_DIRS  = BooleanField('Panorama Cardinal Directions')
    FISH2PANO__DIRS_OFFSET_BOTTOM    = IntegerField('Label Bottom Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    FISH2PANO__OPENCV_FONT_SCALE     = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    FISH2PANO__PIL_FONT_SIZE         = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    IMAGE_SAVE_FITS                  = BooleanField('Save FITS data')
    IMAGE_SAVE_FITS_PERIOD           = SelectField('Periodically save FITS', choices=IMAGE_SAVE_FITS_PERIOD_choices, validators=[IMAGE_SAVE_FITS_PERIOD_validator])
    IMAGE_SAVE_FITS_COMPRESSED       = BooleanField('Compress FITS')
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
    LIGHTGRAPH_OVERLAY__MOONMODE_COLOR = StringField('Moon Mode Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__HOUR_COLOR   = StringField('Hour Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__BORDER_COLOR = StringField('Border Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__NOW_COLOR    = StringField('Time Marker Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__FONT_COLOR   = StringField('Font Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__OPACITY      = IntegerField('Opacity ', validators=[LIGHTGRAPH_OVERLAY__OPACITY_validator])
    LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE = IntegerField('Font Size (Pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    LIGHTGRAPH_OVERLAY__LABEL        = BooleanField('Lightgraph Label')
    LIGHTGRAPH_OVERLAY__HOUR_LINES   = BooleanField('Lightgraph Hour Lines')
    IMAGE_OVERLAY__ENABLE            = BooleanField('Enable Image Overlay')
    IMAGE_OVERLAY__LOAD_INTERVAL     = IntegerField('Download Interval', validators=[IMAGE_OVERLAY__LOAD_INTERVAL_validator])
    IMAGE_OVERLAY__A_URL             = StringField('Source URL', validators=[IMAGE_OVERLAY__URL_validator])
    IMAGE_OVERLAY__A_IMAGE_FILE_TYPE = SelectField('File Type', choices=IMAGE_OVERLAY__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), IMAGE_OVERLAY__IMAGE_FILE_TYPE_validator])
    IMAGE_OVERLAY__A_WIDTH           = IntegerField('Image Width', validators=[IMAGE_OVERLAY__W_H_validator])
    IMAGE_OVERLAY__A_HEIGHT          = IntegerField('Image Height', validators=[IMAGE_OVERLAY__W_H_validator])
    IMAGE_OVERLAY__A_X               = IntegerField('X', validators=[IMAGE_OVERLAY__X_Y_validator])
    IMAGE_OVERLAY__A_Y               = IntegerField('Y', validators=[IMAGE_OVERLAY__X_Y_validator])
    IMAGE_OVERLAY__A_USERNAME        = StringField('Username', validators=[PYCURL_CAMERA__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    IMAGE_OVERLAY__A_PASSWORD        = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[PYCURL_CAMERA__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
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
    IMAGE_STACK_MOONMODE             = BooleanField('Moonmode stacking')
    IMAGE_STACK_DAY                  = BooleanField('Day stacking [debug]')
    BACKUP_DB_PERIOD_DAYS            = IntegerField('DB Backup Frequency (days)', validators=[BACKUP_DB_PERIOD_DAYS_validator])
    IMAGE_EXPIRE_DAYS                = IntegerField('Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    IMAGE_RAW_EXPIRE_DAYS            = IntegerField('RAW Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    IMAGE_FITS_EXPIRE_DAYS           = IntegerField('FITS Image expiration (days)', validators=[DataRequired(), IMAGE_EXPIRE_DAYS_validator])
    TIMELAPSE_EXPIRE_DAYS            = IntegerField('Timelapse expiration (days)', validators=[DataRequired(), TIMELAPSE_EXPIRE_DAYS_validator])
    TIMELAPSE_OVERWRITE              = BooleanField('Allow Overwrite Existing Timelapses')
    FFMPEG_FRAMERATE                 = IntegerField('FFMPEG Framerate (Night)', validators=[DataRequired(), FFMPEG_FRAMERATE_validator])
    FFMPEG_FRAMERATE_DAY             = IntegerField('FFMPEG Framerate (Day)', validators=[DataRequired(), FFMPEG_FRAMERATE_validator])
    FFMPEG_BITRATE                   = StringField('FFMPEG Bitrate (Night)', validators=[DataRequired(), FFMPEG_BITRATE_validator])
    FFMPEG_BITRATE_DAY               = StringField('FFMPEG Bitrate (Day)', validators=[DataRequired(), FFMPEG_BITRATE_validator])
    FFMPEG_VFSCALE                   = SelectField('FFMPEG Scaling (Night)', choices=FFMPEG_VFSCALE_choices, validators=[FFMPEG_VFSCALE_validator])
    FFMPEG_VFSCALE_DAY               = SelectField('FFMPEG Scaling (Day)', choices=FFMPEG_VFSCALE_choices, validators=[FFMPEG_VFSCALE_validator])
    FFMPEG_VFSCALE_STARTRAIL         = SelectField('FFMPEG Scaling (Star Trails)', choices=FFMPEG_VFSCALE_choices, validators=[FFMPEG_VFSCALE_validator])
    FFMPEG_CODEC                     = SelectField('FFMPEG Codec', choices=FFMPEG_CODEC_choices, validators=[FFMPEG_CODEC_validator])
    FFMPEG_EXTRA_OPTIONS             = StringField('FFMPEG Extra Options (Night)', validators=[FFMPEG_EXTRA_OPTIONS_validator])
    FFMPEG_EXTRA_OPTIONS_DAY         = StringField('FFMPEG Extra Options (Day)', validators=[FFMPEG_EXTRA_OPTIONS_validator])
    IMAGE_LABEL_SYSTEM               = SelectField('Label Images', choices=IMAGE_LABEL_SYSTEM_choices, validators=[IMAGE_LABEL_SYSTEM_validator])
    TEXT_PROPERTIES__FONT_FACE       = SelectField('OpenCV Font', choices=TEXT_PROPERTIES__FONT_FACE_choices, validators=[DataRequired(), TEXT_PROPERTIES__FONT_FACE_validator])
    #TEXT_PROPERTIES__FONT_AA
    TEXT_PROPERTIES__FONT_SCALE      = FloatField('Default Font Scale', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    TEXT_PROPERTIES__FONT_THICKNESS  = IntegerField('Font Thickness', validators=[DataRequired(), TEXT_PROPERTIES__FONT_THICKNESS_validator])
    TEXT_PROPERTIES__FONT_OUTLINE    = BooleanField('Font Outline')
    TEXT_PROPERTIES__FONT_HEIGHT     = IntegerField('Text Height Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_HEIGHT_validator])
    TEXT_PROPERTIES__FONT_X          = IntegerField('Text X Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_X_validator])
    TEXT_PROPERTIES__FONT_Y          = IntegerField('Text Y Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_Y_validator])
    TEXT_PROPERTIES__FONT_COLOR      = StringField('Text Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    TEXT_PROPERTIES__PIL_FONT_FILE   = SelectField('Pillow Font', choices=TEXT_PROPERTIES__PIL_FONT_FILE_choices, validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_FILE_validator])
    TEXT_PROPERTIES__PIL_FONT_CUSTOM = StringField('Custom Font', validators=[TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator])
    TEXT_PROPERTIES__PIL_FONT_SIZE   = IntegerField('Default Font Size', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
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
    FILETRANSFER__REMOTE_REALTIME_KEOGRAM_NAME  = StringField('Remote Realtime Keogram Name', validators=[DataRequired(), FILETRANSFER__REMOTE_NAME_validator])
    FILETRANSFER__REMOTE_REALTIME_KEOGRAM_FOLDER = StringField('Remote Realtime Keogram Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER      = StringField('Remote EndOfNight Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_LATEST_FOLDER          = StringField('Remote Latest Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__REMOTE_DB_BACKUP_FOLDER       = StringField('Remote DB Backup Folder', validators=[DataRequired(), FILETRANSFER__REMOTE_FOLDER_validator])
    FILETRANSFER__UPLOAD_IMAGE       = IntegerField('Transfer images', validators=[FILETRANSFER__UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_PANORAMA    = IntegerField('Transfer panoramas', validators=[FILETRANSFER__UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_METADATA    = BooleanField('Transfer metadata')
    FILETRANSFER__UPLOAD_RAW         = BooleanField('Transfer RAW')
    FILETRANSFER__UPLOAD_FITS        = BooleanField('Transfer FITS')
    FILETRANSFER__UPLOAD_VIDEO       = BooleanField('Transfer timelapses')
    FILETRANSFER__UPLOAD_MINI_VIDEO  = BooleanField('Transfer mini timelapses')
    FILETRANSFER__UPLOAD_KEOGRAM     = BooleanField('Transfer keograms')
    FILETRANSFER__UPLOAD_STARTRAIL   = BooleanField('Transfer star trails')
    FILETRANSFER__UPLOAD_STARTRAIL_VIDEO    = BooleanField('Transfer star trail videos')
    FILETRANSFER__UPLOAD_PANORAMA_VIDEO     = BooleanField('Transfer panorama videos')
    FILETRANSFER__UPLOAD_REALTIME_KEOGRAM   = IntegerField('Transfer realtime keograms', validators=[FILETRANSFER__UPLOAD_IMAGE_validator])
    FILETRANSFER__UPLOAD_ENDOFNIGHT         = BooleanField('Transfer AllSky EndOfNight data')
    FILETRANSFER__UPLOAD_LATEST_IMAGE       = BooleanField('Transfer Latest Image')
    FILETRANSFER__UPLOAD_LATEST_PANORAMA    = BooleanField('Transfer Latest Panorama Image')
    FILETRANSFER__UPLOAD_LATEST_RAW         = BooleanField('Transfer Latest RAW Image')
    FILETRANSFER__UPLOAD_LATEST_VIDEO       = BooleanField('Transfer Latest Timelapse Assets')
    FILETRANSFER__UPLOAD_DB_BACKUP          = BooleanField('Transfer DB Backups')
    S3UPLOAD__CLASSNAME              = SelectField('S3 Utility', choices=S3UPLOAD__CLASSNAME_choices, validators=[DataRequired(), S3UPLOAD__CLASSNAME_validator])
    S3UPLOAD__ENABLE                 = BooleanField('Enable S3 Uploading')
    S3UPLOAD__ACCESS_KEY             = StringField('Access Key', validators=[S3UPLOAD__ACCESS_KEY_validator])
    S3UPLOAD__SECRET_KEY             = PasswordField('Secret Key', widget=PasswordInput(hide_value=False), validators=[S3UPLOAD__SECRET_KEY_validator])
    S3UPLOAD__CREDS_FILE             = StringField('Credentials File', validators=[S3UPLOAD__CREDS_FILE_validator])
    S3UPLOAD__BUCKET                 = StringField('Bucket', validators=[DataRequired(), S3UPLOAD__BUCKET_validator])
    S3UPLOAD__REGION                 = StringField('Region', validators=[S3UPLOAD__REGION_validator])
    S3UPLOAD__NAMESPACE              = StringField('Namespace', validators=[S3UPLOAD__NAMESPACE_validator])
    S3UPLOAD__ENDPOINT_URL           = StringField('Endpoint URL', validators=[S3UPLOAD__ENDPOINT_URL_validator])
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
    MQTTPUBLISH__PROTOCOL            = SelectField('MQTT Protocol', choices=MQTTPUBLISH__PROTOCOL_choices, validators=[DataRequired(), MQTTPUBLISH__PROTOCOL_validator])
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
    ALLSKYMAP__ENABLE                = BooleanField('Enable Allsky Map Ping')
    ALLSKYMAP__API_URL               = StringField('API URL', validators=[ALLSKYMAP__API_URL_validator])
    ALLSKYMAP__API_KEY               = PasswordField('API Key', widget=PasswordInput(hide_value=False), validators=[ALLSKYMAP__API_KEY_validator], render_kw={'autocomplete' : 'new-password'})
    ALLSKYMAP__CAMERA_NAME           = StringField('Camera Name')
    ALLSKYMAP__CAMERA_OWNER          = StringField('Camera Owner')
    ALLSKYMAP__WEBSITE_URL           = StringField('Website URL')
    ALLSKYMAP__UPLOAD_IMAGE          = BooleanField('Upload Latest Image')
    ALLSKYMAP__INTERVAL              = IntegerField('Interval (Minutes)', validators=[ALLSKYMAP__INTERVAL_validator])
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
    LIBCAMERA__IMAGE_FILE_TYPE       = SelectField('libcamera image type (Night)', choices=LIBCAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), LIBCAMERA__IMAGE_FILE_TYPE_validator])
    LIBCAMERA__IMAGE_FILE_TYPE_DAY   = SelectField('libcamera image type (Day)', choices=LIBCAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), LIBCAMERA__IMAGE_FILE_TYPE_validator])
    LIBCAMERA__IMMEDIATE             = BooleanField('Immediate Flag (Night)')
    LIBCAMERA__IMMEDIATE_DAY         = BooleanField('Immediate Flag (Day)')
    LIBCAMERA__AWB                   = SelectField('AWB (Night)', choices=LIBCAMERA__AWB_choices, validators=[DataRequired(), LIBCAMERA__AWB_validator])
    LIBCAMERA__AWB_DAY               = SelectField('AWB (Day)', choices=LIBCAMERA__AWB_choices, validators=[DataRequired(), LIBCAMERA__AWB_validator])
    LIBCAMERA__AWB_ENABLE            = BooleanField('Enable AWB (Night)')
    LIBCAMERA__AWB_ENABLE_DAY        = BooleanField('Enable AWB (Day)')
    LIBCAMERA__CCM_DISABLE           = BooleanField('Disable Color Correction Matrix (Night)')
    LIBCAMERA__CCM_DISABLE_DAY       = BooleanField('Disable Color Correction Matrix (Day)')
    LIBCAMERA__CAMERA_ID             = SelectField('Camera ID', choices=LIBCAMERA__CAMERA_ID_choices, validators=[LIBCAMERA__CAMERA_ID_validator])
    LIBCAMERA__EXTRA_OPTIONS         = StringField('Night libcamera extra options', validators=[LIBCAMERA__EXTRA_OPTIONS_validator])
    LIBCAMERA__EXTRA_OPTIONS_DAY     = StringField('Day libcamera extra options', validators=[LIBCAMERA__EXTRA_OPTIONS_validator])
    LIBCAMERA__MQTT_TRANSPORT        = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    LIBCAMERA__MQTT_PROTOCOL         = SelectField('MQTT Protocol', choices=MQTTPUBLISH__PROTOCOL_choices, validators=[DataRequired(), MQTTPUBLISH__PROTOCOL_validator])
    LIBCAMERA__MQTT_HOST             = StringField('MQTT Host (libcamera)', validators=[MQTTPUBLISH__HOST_validator])
    LIBCAMERA__MQTT_PORT             = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    LIBCAMERA__MQTT_USERNAME         = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    LIBCAMERA__MQTT_PASSWORD         = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    LIBCAMERA__MQTT_QOS              = IntegerField('MQTT QoS', validators=[MQTTPUBLISH__QOS_validator])
    LIBCAMERA__MQTT_TLS              = BooleanField('Use TLS')
    LIBCAMERA__MQTT_CERT_BYPASS      = BooleanField('Disable Certificate Validation')
    LIBCAMERA__MQTT_EXPOSURE_TOPIC   = StringField('libcamera Exposure Topic', validators=[DataRequired(), MQTTPUBLISH__TOPIC_validator])
    LIBCAMERA__MQTT_IMAGE_TOPIC      = StringField('libcamera Image (Return) Topic', validators=[DataRequired(), MQTTPUBLISH__TOPIC_validator])
    LIBCAMERA__MQTT_METADATA_TOPIC   = StringField('libcamera Metadata (Return) Topic', validators=[DataRequired(), MQTTPUBLISH__TOPIC_validator])
    PYCURL_CAMERA__URL               = StringField('libcamera pyCurl Camera URL', validators=[PYCURL_CAMERA__URL_validator])
    PYCURL_CAMERA__IMAGE_FILE_TYPE   = SelectField('File Type', choices=PYCURL_CAMERA__IMAGE_FILE_TYPE_choices, validators=[DataRequired(), PYCURL_CAMERA__IMAGE_FILE_TYPE_validator])
    PYCURL_CAMERA__USERNAME          = StringField('Username', validators=[PYCURL_CAMERA__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    PYCURL_CAMERA__PASSWORD          = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[PYCURL_CAMERA__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    ACCUM_CAMERA__SUB_EXPOSURE_MAX   = FloatField('Accumulator Max Sub-exposure', validators=[DataRequired(), ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator])
    ACCUM_CAMERA__EVEN_EXPOSURES     = BooleanField('Accumulator Even Exposures')
    ACCUM_CAMERA__CLAMP_16BIT        = BooleanField('Accumulator Clamp 16-bit')
    TEST_CAMERA__WIDTH                  = IntegerField('Test Camera - Width', validators=[DataRequired(), TEST_CAMERA__WIDTH_validator])
    TEST_CAMERA__HEIGHT                 = IntegerField('Test Camera - Height', validators=[DataRequired(), TEST_CAMERA__HEIGHT_validator])
    TEST_CAMERA__IMAGE_CIRCLE_DIAMETER  = IntegerField('Test Camera - Image Circle Diameter', validators=[TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator])
    TEST_CAMERA__IMAGE_CIRCLE_OFFSET_X  = IntegerField('Test Camera - Image Circle X Offset', validators=[TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator])
    TEST_CAMERA__IMAGE_CIRCLE_OFFSET_Y  = IntegerField('Test Camera - Image Circle Y Offset', validators=[TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator])
    TEST_CAMERA__ROTATING_STAR_COUNT    = IntegerField('Test Camera - Rotating Star Count', validators=[DataRequired(), TEST_CAMERA__ROTATING_STAR_COUNT_validator])
    TEST_CAMERA__ROTATING_STAR_FACTOR   = FloatField('Test Camera - Rotating Star Rotation Factor', validators=[DataRequired(), TEST_CAMERA__ROTATING_STAR_FACTOR_validator])
    TEST_CAMERA__BUBBLE_COUNT           = IntegerField('Test Camera - Bubble Count', validators=[DataRequired(), TEST_CAMERA__BUBBLE_COUNT_validator])
    VIRTUALSKY__MAGNITUDE               = FloatField('VirtualSky Limiting Magnitude', validators=[VIRTUALSKY__MAGNITUDE_validator], widget=NumberInput(step=0.25))
    VIRTUALSKY__CONSTELLATIONS          = BooleanField('Show Constellations')
    VIRTUALSKY__CONSTELLATIONLABELS     = BooleanField('Constellation Labels')
    VIRTUALSKY__SHOWSTARS               = BooleanField('Show Stars')
    VIRTUALSKY__SHOWSTARLABELS          = BooleanField('Star Labels')
    VIRTUALSKY__SHOWPLANETS             = BooleanField('Show Planets')
    VIRTUALSKY__SHOWPLANETLABELS        = BooleanField('Planet Labels')
    VIRTUALSKY__IMAGE_CIRCLE_DIAMETER   = IntegerField('Image Circle', validators=[VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator])
    VIRTUALSKY__LATITUDE_OFFSET         = FloatField('VirtualSky Latitude Offset', validators=[VIRTUALSKY__LATITUDE_OFFSET_validator], widget=NumberInput(step=0.25))
    VIRTUALSKY__LONGITUDE_OFFSET        = FloatField('VirtualSky Longitude Offset', validators=[VIRTUALSKY__LONGITUDE_OFFSET_validator], widget=NumberInput(step=0.25))
    VIRTUALSKY__OFFSET_X                = IntegerField('X Offset', validators=[VIRTUALSKY__OFFSET_X_validator])
    VIRTUALSKY__OFFSET_Y                = IntegerField('Y Offset', validators=[VIRTUALSKY__OFFSET_Y_validator])
    #VIRTUALSKY__FLIP_NS                 = BooleanField('Flip North/South')
    #VIRTUALSKY__FLIP_EW                 = BooleanField('Flip East/West')
    CIRCULAR_DISPLAY__ENABLE         = BooleanField('Enable Circular Display Output')
    CIRCULAR_DISPLAY__RESOLUTION     = SelectField('Resolution', choices=CIRCULAR_DISPLAY__RESOLUTION_choices, validators=[DataRequired(), CIRCULAR_DISPLAY__RESOLUTION_validator])
    CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER  = IntegerField('Image Circle', validators=[CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator])
    FOCUSER__CLASSNAME               = SelectField('Focuser', choices=FOCUSER__CLASSNAME_choices, validators=[FOCUSER__CLASSNAME_validator])
    FOCUSER__GPIO_PIN_1              = StringField('GPIO Pin 1', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_2              = StringField('GPIO Pin 2', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_3              = StringField('GPIO Pin 3', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__GPIO_PIN_4              = StringField('GPIO Pin 4', validators=[DEVICE_PIN_NAME_validator])
    FOCUSER__I2C_ADDRESS             = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    DEW_HEATER__CLASSNAME            = SelectField('Dew Heater', choices=DEW_HEATER__CLASSNAME_choices, validators=[DEW_HEATER__CLASSNAME_validator])
    DEW_HEATER__ENABLE_DAY           = BooleanField('Enable Daytime')
    DEW_HEATER__I2C_ADDRESS          = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    DEW_HEATER__PIN_1                = StringField('Pin', validators=[DEVICE_PIN_NAME_validator])
    DEW_HEATER__INVERT_OUTPUT        = BooleanField('Invert Output')
    DEW_HEATER__LEVEL_DEF            = IntegerField('Default Level', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__THOLD_ENABLE         = BooleanField('Enable Dew Heater Thresholds')
    DEW_HEATER__MANUAL_TARGET        = FloatField('Manual Target', validators=[DEW_HEATER__MANUAL_TARGET_validator])
    DEW_HEATER__TEMP_USER_VAR_SLOT   = SelectField('Temperature Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    DEW_HEATER__DEWPOINT_USER_VAR_SLOT = SelectField('Target Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    DEW_HEATER__LEVEL_LOW            = IntegerField('Low Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__LEVEL_MED            = IntegerField('Medium Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__LEVEL_HIGH           = IntegerField('High Setting', validators=[DEW_HEATER__LEVEL_validator])
    DEW_HEATER__THOLD_DIFF_LOW       = StringField('Low Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    DEW_HEATER__THOLD_DIFF_MED       = StringField('Medium Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    DEW_HEATER__THOLD_DIFF_HIGH      = StringField('High Threshold Delta', validators=[DEW_HEATER__THOLD_DIFF_validator])
    DEW_HEATER__HOLD_SECONDS         = IntegerField('Change Hold Time (seconds)', validators=[DEW_HEATER__HOLD_SECONDS_validator])
    DEW_HEATER__PWM_FREQUENCY        = IntegerField('PWM Frequency', validators=[PWM_FREQUENCY_validator])
    FAN__CLASSNAME                   = SelectField('Fan', choices=FAN__CLASSNAME_choices, validators=[FAN__CLASSNAME_validator])
    FAN__ENABLE_NIGHT                = BooleanField('Enable Night')
    FAN__I2C_ADDRESS                 = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    FAN__PIN_1                       = StringField('Pin', validators=[DEVICE_PIN_NAME_validator])
    FAN__INVERT_OUTPUT               = BooleanField('Invert Output')
    FAN__LEVEL_DEF                   = IntegerField('Default Level', validators=[FAN__LEVEL_validator])
    FAN__THOLD_ENABLE                = BooleanField('Enable Fan Thresholds')
    FAN__TARGET                      = FloatField('Target Temp', validators=[FAN__TARGET_validator])
    FAN__TEMP_USER_VAR_SLOT          = SelectField('Temperature Sensor Slot', choices=[], validators=[SENSOR_SLOT_validator])
    FAN__LEVEL_LOW                   = IntegerField('Low Setting', validators=[FAN__LEVEL_validator])
    FAN__LEVEL_MED                   = IntegerField('Medium Setting', validators=[FAN__LEVEL_validator])
    FAN__LEVEL_HIGH                  = IntegerField('High Setting', validators=[FAN__LEVEL_validator])
    FAN__THOLD_DIFF_LOW              = StringField('Low Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    FAN__THOLD_DIFF_MED              = StringField('Medium Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    FAN__THOLD_DIFF_HIGH             = StringField('High Threshold Delta', validators=[FAN__THOLD_DIFF_validator])
    FAN__HOLD_SECONDS                = IntegerField('Change Hold Time (seconds)', validators=[FAN__HOLD_SECONDS_validator])
    FAN__PWM_FREQUENCY               = IntegerField('PWM Frequency', validators=[PWM_FREQUENCY_validator])
    GENERIC_GPIO__A_CLASSNAME        = SelectField('Automated GPIO', choices=GENERIC_GPIO__CLASSNAME_choices, validators=[GENERIC_GPIO__CLASSNAME_validator])
    GENERIC_GPIO__A_I2C_ADDRESS      = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    GENERIC_GPIO__A_PIN_1            = StringField('Pin/Port', validators=[DEVICE_PIN_NAME_validator])
    GENERIC_GPIO__A_INVERT_OUTPUT    = BooleanField('Invert Output')
    MANUAL_GPIO__A_CLASSNAME         = SelectField('Manual GPIO Class', choices=MANUAL_GPIO__CLASSNAME_choices, validators=[MANUAL_GPIO__CLASSNAME_validator])
    MANUAL_GPIO__A_PIN_1             = StringField('Manual Pin 1', validators=[DEVICE_PIN_NAME_validator])
    MANUAL_GPIO__A_PIN_2             = StringField('Manual Pin 2', validators=[DEVICE_PIN_NAME_validator])
    MANUAL_GPIO__A_PIN_3             = StringField('Manual Pin 3', validators=[DEVICE_PIN_NAME_validator])
    DEVICE__MQTT_TRANSPORT           = SelectField('MQTT Transport', choices=MQTTPUBLISH__TRANSPORT_choices, validators=[DataRequired(), MQTTPUBLISH__TRANSPORT_validator])
    DEVICE__MQTT_PROTOCOL            = SelectField('MQTT Protocol', choices=MQTTPUBLISH__PROTOCOL_choices, validators=[DataRequired(), MQTTPUBLISH__PROTOCOL_validator])
    DEVICE__MQTT_HOST                = StringField('MQTT Host', validators=[MQTTPUBLISH__HOST_validator])
    DEVICE__MQTT_PORT                = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    DEVICE__MQTT_USERNAME            = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    DEVICE__MQTT_PASSWORD            = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    DEVICE__MQTT_QOS                 = IntegerField('MQTT QoS', validators=[MQTTPUBLISH__QOS_validator])
    DEVICE__MQTT_TLS                 = BooleanField('Use TLS')
    DEVICE__MQTT_CERT_BYPASS         = BooleanField('Disable Certificate Validation')
    TEMP_SENSOR__A_CLASSNAME         = SelectField('Sensor A', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__A_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__A_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__A_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__A_USER_VAR_SLOT     = SelectField('Sensor A Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__A_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__A_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__B_CLASSNAME         = SelectField('Sensor B', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__B_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__B_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__B_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__B_USER_VAR_SLOT     = SelectField('Sensor B Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__B_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__B_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__C_CLASSNAME         = SelectField('Sensor C', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__C_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__C_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__C_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__C_USER_VAR_SLOT     = SelectField('Sensor C Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__C_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__C_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__D_CLASSNAME         = SelectField('Sensor D', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__D_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__D_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__D_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__D_USER_VAR_SLOT     = SelectField('Sensor D Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__D_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__D_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__E_CLASSNAME         = SelectField('Sensor E', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__E_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__E_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__E_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__E_USER_VAR_SLOT     = SelectField('Sensor E Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__E_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__E_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__F_CLASSNAME         = SelectField('Sensor F', choices=TEMP_SENSOR__CLASSNAME_choices, validators=[TEMP_SENSOR__CLASSNAME_validator])
    TEMP_SENSOR__F_LABEL             = StringField('Label', validators=[DataRequired(), TEMP_SENSOR__LABEL_validator])
    TEMP_SENSOR__F_PIN_1             = StringField('Pin/Port 1', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__F_PIN_2             = StringField('Pin/Port 2', validators=[DEVICE_PIN_NAME_validator])
    TEMP_SENSOR__F_USER_VAR_SLOT     = SelectField('Sensor F Initial Slot', choices=SENSOR_USER_VAR_SLOT_choices, validators=[SENSOR_USER_VAR_SLOT_validator])
    TEMP_SENSOR__F_I2C_ADDRESS       = StringField('I2C Address', validators=[DataRequired(), I2C_ADDRESS_validator])
    TEMP_SENSOR__F_TITLE_TEMPLATE    = StringField('Chart Title Template', validators=[DataRequired(), TEMP_SENSOR__TITLE_TEMPLATE_validator])
    TEMP_SENSOR__FC37_ACTIVE_LOW     = BooleanField('Rain Sensor FC-37 - Invert logic')
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
    TEMP_SENSOR__MQTT_PROTOCOL       = SelectField('MQTT Protocol', choices=MQTTPUBLISH__PROTOCOL_choices, validators=[DataRequired(), MQTTPUBLISH__PROTOCOL_validator])
    TEMP_SENSOR__MQTT_HOST           = StringField('MQTT Host', validators=[MQTTPUBLISH__HOST_validator])
    TEMP_SENSOR__MQTT_PORT           = IntegerField('Port', validators=[DataRequired(), MQTTPUBLISH__PORT_validator])
    TEMP_SENSOR__MQTT_USERNAME       = StringField('Username', validators=[MQTTPUBLISH__USERNAME_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__MQTT_PASSWORD       = PasswordField('Password', widget=PasswordInput(hide_value=False), validators=[MQTTPUBLISH__PASSWORD_validator], render_kw={'autocomplete' : 'new-password'})
    TEMP_SENSOR__MQTT_TLS            = BooleanField('Use TLS')
    TEMP_SENSOR__MQTT_CERT_BYPASS    = BooleanField('Disable Certificate Validation')
    TEMP_SENSOR__DHT_USE_PULSEIO     = BooleanField('DHT11/21/22 - use_pulseio')
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
    TEMP_SENSOR__TSL2561_DISABLE_DAY = BooleanField('TSL2561 Disable Daytime')
    TEMP_SENSOR__TSL2591_GAIN_NIGHT  = SelectField('TSL2591 Gain (Night)', choices=TEMP_SENSOR__TSL2591_GAIN_choices, validators=[TEMP_SENSOR__TSL2591_GAIN_validator])
    TEMP_SENSOR__TSL2591_GAIN_DAY    = SelectField('TSL2591 Gain (Day)', choices=TEMP_SENSOR__TSL2591_GAIN_choices, validators=[TEMP_SENSOR__TSL2591_GAIN_validator])
    TEMP_SENSOR__TSL2591_INT_NIGHT   = SelectField('TSL2591 Integration (Night)', choices=TEMP_SENSOR__TSL2591_INT_choices, validators=[TEMP_SENSOR__TSL2591_INT_validator])
    TEMP_SENSOR__TSL2591_INT_DAY     = SelectField('TSL2591 Integration (Day)', choices=TEMP_SENSOR__TSL2591_INT_choices, validators=[TEMP_SENSOR__TSL2591_INT_validator])
    TEMP_SENSOR__TSL2591_DISABLE_DAY = BooleanField('TSL2591 Disable Daytime')
    TEMP_SENSOR__VEML7700_GAIN_NIGHT = SelectField('VEML7700 Gain (Night)', choices=TEMP_SENSOR__VEML7700_GAIN_choices, validators=[TEMP_SENSOR__VEML7700_GAIN_validator])
    TEMP_SENSOR__VEML7700_GAIN_DAY   = SelectField('VEML7700 Gain (Day)', choices=TEMP_SENSOR__VEML7700_GAIN_choices, validators=[TEMP_SENSOR__VEML7700_GAIN_validator])
    TEMP_SENSOR__VEML7700_INT_NIGHT  = SelectField('VEML7700 Integration (Night)', choices=TEMP_SENSOR__VEML7700_INT_choices, validators=[TEMP_SENSOR__VEML7700_INT_validator])
    TEMP_SENSOR__VEML7700_INT_DAY    = SelectField('VEML7700 Integration (Day)', choices=TEMP_SENSOR__VEML7700_INT_choices, validators=[TEMP_SENSOR__VEML7700_INT_validator])
    TEMP_SENSOR__SI1145_VIS_GAIN_NIGHT = SelectField('SI1145 Visible Gain (Night)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_VIS_GAIN_DAY   = SelectField('SI1145 Visible Gain (Day)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_IR_GAIN_NIGHT  = SelectField('SI1145 IR Gain (Night)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_IR_GAIN_DAY    = SelectField('SI1145 IR Gain (Day)', choices=TEMP_SENSOR__SI1145_GAIN_choices, validators=[TEMP_SENSOR__SI1145_GAIN_validator])
    TEMP_SENSOR__SI1145_VIS_RANGE_HIGH_NIGHT = BooleanField('SI1145 Visible Range High (Night)')
    TEMP_SENSOR__SI1145_VIS_RANGE_HIGH_DAY   = BooleanField('SI1145 Visible Range High (Day)')
    TEMP_SENSOR__SI1145_IR_RANGE_HIGH_NIGHT  = BooleanField('SI1145 IR Range High (Night)')
    TEMP_SENSOR__SI1145_IR_RANGE_HIGH_DAY    = BooleanField('SI1145 IR Range High (Day)')
    TEMP_SENSOR__LTR390_GAIN_NIGHT     = SelectField('LTR390 Gain (Night)', choices=TEMP_SENSOR__LTR390_GAIN_choices, validators=[TEMP_SENSOR__LTR390_GAIN_validator])
    TEMP_SENSOR__LTR390_GAIN_DAY       = SelectField('LTR390 Gain (Day)', choices=TEMP_SENSOR__LTR390_GAIN_choices, validators=[TEMP_SENSOR__LTR390_GAIN_validator])
    TEMP_SENSOR__INA3221_CH1_ENABLE    = BooleanField('INA3221 Channel 1')
    TEMP_SENSOR__INA3221_CH2_ENABLE    = BooleanField('INA3221 Channel 2')
    TEMP_SENSOR__INA3221_CH3_ENABLE    = BooleanField('INA3221 Channel 3')
    TEMP_SENSOR__AS3935_OUTDOOR_MODE    = BooleanField('AS3935 Outdoor Mode')
    TEMP_SENSOR__AS3935_MASK_DISTURBER  = BooleanField('AS3935 Mask Disturber')
    TEMP_SENSOR__AS3935_NOISE_LEVEL     = IntegerField('AS3935 Noise Level Threshold', validators=[DataRequired(), TEMP_SENSOR__AS3935_NOISE_LEVEL_validator])
    TEMP_SENSOR__AS3935_SPIKE_REJECTION = IntegerField('AS3935 Spike Rejection', validators=[DataRequired(), TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator])
    TEMP_SENSOR__LUX_MAGNITUDE_OFFSET   = FloatField('Lux Magnitude Offset', validators=[SQM_MAGNITUDE_OFFSET_validator])
    CHARTS__CUSTOM_SLOT_1            = SelectField('Extra Chart Slot 1', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_1_MIN        = FloatField('Chart 1 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_2            = SelectField('Extra Chart Slot 2', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_2_MIN        = FloatField('Chart 2 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_3            = SelectField('Extra Chart Slot 3', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_3_MIN        = FloatField('Chart 3 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_4            = SelectField('Extra Chart Slot 4', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_4_MIN        = FloatField('Chart 4 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_5            = SelectField('Extra Chart Slot 5', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_5_MIN        = FloatField('Chart 5 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_6            = SelectField('Extra Chart Slot 6', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_6_MIN        = FloatField('Chart 6 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_7            = SelectField('Extra Chart Slot 7', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_7_MIN        = FloatField('Chart 7 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_8            = SelectField('Extra Chart Slot 8', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_8_MIN        = FloatField('Chart 8 Minimum', validators=[CUSTOM_CHART_MIN_validator])
    CHARTS__CUSTOM_SLOT_9            = SelectField('Extra Chart Slot 9', choices=[], validators=[CUSTOM_CHART_validator])
    CHARTS__CUSTOM_SLOT_9_MIN        = FloatField('Chart 9 Minimum', validators=[CUSTOM_CHART_MIN_validator])
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
    LOCAL_AUTH_ENABLE                = BooleanField('Enable Local Authentication')
    CONFIG_NOTE                      = StringField('Config Note')

    ADMIN_NETWORKS_FLASK             = TextAreaField('Admin Networks', render_kw={'readonly' : True, 'disabled' : 'disabled'})


    def __init__(self, *args, **kwargs):
        super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)

        from ..devices import sensors as indi_allsky_sensors

        data = kwargs['data']


        temp_sensor__a_classname = str(data['TEMP_SENSOR__A_CLASSNAME'])
        temp_sensor__a_label = str(data['TEMP_SENSOR__A_LABEL'])
        temp_sensor__a_user_var_slot = str(data['TEMP_SENSOR__A_USER_VAR_SLOT'])
        temp_sensor__a_pin_1_name = str(data['TEMP_SENSOR__A_PIN_1'])

        temp_sensor__b_classname = str(data['TEMP_SENSOR__B_CLASSNAME'])
        temp_sensor__b_label = str(data['TEMP_SENSOR__B_LABEL'])
        temp_sensor__b_user_var_slot = str(data['TEMP_SENSOR__B_USER_VAR_SLOT'])
        temp_sensor__b_pin_1_name = str(data['TEMP_SENSOR__B_PIN_1'])

        temp_sensor__c_classname = str(data['TEMP_SENSOR__C_CLASSNAME'])
        temp_sensor__c_label = str(data['TEMP_SENSOR__C_LABEL'])
        temp_sensor__c_user_var_slot = str(data['TEMP_SENSOR__C_USER_VAR_SLOT'])
        temp_sensor__c_pin_1_name = str(data['TEMP_SENSOR__C_PIN_1'])

        temp_sensor__d_classname = str(data['TEMP_SENSOR__D_CLASSNAME'])
        temp_sensor__d_label = str(data['TEMP_SENSOR__D_LABEL'])
        temp_sensor__d_user_var_slot = str(data['TEMP_SENSOR__D_USER_VAR_SLOT'])
        temp_sensor__d_pin_1_name = str(data['TEMP_SENSOR__D_PIN_1'])

        temp_sensor__e_classname = str(data['TEMP_SENSOR__E_CLASSNAME'])
        temp_sensor__e_label = str(data['TEMP_SENSOR__E_LABEL'])
        temp_sensor__e_user_var_slot = str(data['TEMP_SENSOR__E_USER_VAR_SLOT'])
        temp_sensor__e_pin_1_name = str(data['TEMP_SENSOR__E_PIN_1'])

        temp_sensor__f_classname = str(data['TEMP_SENSOR__F_CLASSNAME'])
        temp_sensor__f_label = str(data['TEMP_SENSOR__F_LABEL'])
        temp_sensor__f_user_var_slot = str(data['TEMP_SENSOR__F_USER_VAR_SLOT'])
        temp_sensor__f_pin_1_name = str(data['TEMP_SENSOR__F_PIN_1'])


        if temp_sensor__a_classname:
            try:
                temp_sensor__a_class = getattr(indi_allsky_sensors, temp_sensor__a_classname)
                slot_a_index = constants.SENSOR_INDEX_MAP[temp_sensor__a_user_var_slot]
                temp_sensor__a_labels = temp_sensor__a_class.get_labels(temp_sensor__a_pin_1_name)

                for x in range(temp_sensor__a_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_a_index + x,
                            'name'  : temp_sensor__a_class.METADATA['name'],
                            'label' : temp_sensor__a_label,
                            'probe' : temp_sensor__a_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_a_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__a_classname)


        if temp_sensor__b_classname:
            try:
                temp_sensor__b_class = getattr(indi_allsky_sensors, temp_sensor__b_classname)
                slot_b_index = constants.SENSOR_INDEX_MAP[temp_sensor__b_user_var_slot]
                temp_sensor__b_labels = temp_sensor__b_class.get_labels(temp_sensor__b_pin_1_name)

                for x in range(temp_sensor__b_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_b_index + x,
                            'name'  : temp_sensor__b_class.METADATA['name'],
                            'label' : temp_sensor__b_label,
                            'probe' : temp_sensor__b_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_b_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__b_classname)


        if temp_sensor__c_classname:
            try:
                temp_sensor__c_class = getattr(indi_allsky_sensors, temp_sensor__c_classname)
                slot_c_index = constants.SENSOR_INDEX_MAP[temp_sensor__c_user_var_slot]
                temp_sensor__c_labels = temp_sensor__c_class.get_labels(temp_sensor__c_pin_1_name)

                for x in range(temp_sensor__c_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_c_index + x,
                            'name'  : temp_sensor__c_class.METADATA['name'],
                            'label' : temp_sensor__c_label,
                            'probe' : temp_sensor__c_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_c_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__c_classname)


        if temp_sensor__d_classname:
            try:
                temp_sensor__d_class = getattr(indi_allsky_sensors, temp_sensor__d_classname)
                slot_d_index = constants.SENSOR_INDEX_MAP[temp_sensor__d_user_var_slot]
                temp_sensor__d_labels = temp_sensor__d_class.get_labels(temp_sensor__d_pin_1_name)

                for x in range(temp_sensor__d_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_d_index + x,
                            'name'  : temp_sensor__d_class.METADATA['name'],
                            'label' : temp_sensor__d_label,
                            'probe' : temp_sensor__d_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_d_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__d_classname)


        if temp_sensor__e_classname:
            try:
                temp_sensor__e_class = getattr(indi_allsky_sensors, temp_sensor__e_classname)
                slot_e_index = constants.SENSOR_INDEX_MAP[temp_sensor__e_user_var_slot]
                temp_sensor__e_labels = temp_sensor__e_class.get_labels(temp_sensor__e_pin_1_name)

                for x in range(temp_sensor__e_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_e_index + x,
                            'name'  : temp_sensor__e_class.METADATA['name'],
                            'label' : temp_sensor__e_label,
                            'probe' : temp_sensor__e_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_e_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__e_classname)


        if temp_sensor__f_classname:
            try:
                temp_sensor__f_class = getattr(indi_allsky_sensors, temp_sensor__f_classname)
                slot_f_index = constants.SENSOR_INDEX_MAP[temp_sensor__f_user_var_slot]
                temp_sensor__f_labels = temp_sensor__f_class.get_labels(temp_sensor__f_pin_1_name)

                for x in range(temp_sensor__f_class.METADATA['count']):
                    try:
                        sensor_label_data = {
                            'index' : slot_f_index + x,
                            'name'  : temp_sensor__f_class.METADATA['name'],
                            'label' : temp_sensor__f_label,
                            'probe' : temp_sensor__f_labels[x],
                        }

                        self.SENSOR_SLOT_choices['User Sensors'][slot_f_index + x][1] = '({index:d}) {name:s} - {label:s} - {probe:s}'.format(**sensor_label_data)
                    except IndexError:
                        app.logger.error('Not enough slots for sensor values')
                        pass
            except AttributeError:
                app.logger.error('Unknown sensor class: %s', temp_sensor__f_classname)


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


        for x, label in enumerate(temp_label_list[:50]):  # limit to 50
            self.SENSOR_SLOT_choices['System Sensors'][x + 10][1] = '({0:d}) {1:s}'.format(x + 10, label)


        ### Update the choices
        self.DEW_HEATER__TEMP_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices
        self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices
        self.FAN__TEMP_USER_VAR_SLOT.choices = self.SENSOR_SLOT_choices

        # Merge dictionaries
        self.CUSTOM_CHART_choices.update(self.SENSOR_SLOT_choices)
        self.CHARTS__CUSTOM_SLOT_1.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_2.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_3.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_4.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_5.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_6.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_7.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_8.choices = self.CUSTOM_CHART_choices
        self.CHARTS__CUSTOM_SLOT_9.choices = self.CUSTOM_CHART_choices


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


        if self.CAMERA_INTERFACE.data == 'pycurl_camera':
            if not self.PYCURL_CAMERA__URL.data:
                self.PYCURL_CAMERA__URL.errors.append('URL cannot blank')
                result = False


        # require custom font to be defined
        if self.TEXT_PROPERTIES__PIL_FONT_FILE.data == 'custom':
            if not self.TEXT_PROPERTIES__PIL_FONT_CUSTOM.data:
                self.TEXT_PROPERTIES__PIL_FONT_CUSTOM.errors.append('Please set a custom font')
                result = False


        if self.ADU_ROI_X1.data and self.ADU_ROI_Y1.data and self.ADU_ROI_X2.data and self.ADU_ROI_Y2.data:
            if self.ADU_ROI_X2.data <= self.ADU_ROI_X1.data:
                self.ADU_ROI_X2.errors.append('X2 must be greater than X1')
                result = False

            if self.ADU_ROI_Y2.data <= self.ADU_ROI_Y1.data:
                self.ADU_ROI_Y2.errors.append('Y2 must be greater than Y1')
                result = False



        if self.IMAGE_CROP_ROI_X1.data and self.IMAGE_CROP_ROI_Y1.data and self.IMAGE_CROP_ROI_X2.data and self.IMAGE_CROP_ROI_Y2.data:
            if self.IMAGE_CROP_ROI_X2.data <= self.IMAGE_CROP_ROI_X1.data:
                self.IMAGE_CROP_ROI_X2.errors.append('X2 must be greater than X1')
                result = False

            if self.IMAGE_CROP_ROI_Y2.data <= self.IMAGE_CROP_ROI_Y1.data:
                self.IMAGE_CROP_ROI_Y2.errors.append('Y2 must be greater than Y1')
                result = False


        if self.SQM_ROI_X1.data and self.SQM_ROI_Y1.data and self.SQM_ROI_X2.data and self.SQM_ROI_Y2.data:
            if self.SQM_ROI_X2.data <= self.SQM_ROI_X1.data:
                self.SQM_ROI_X2.errors.append('X2 must be greater than X1')
                result = False

            if self.SQM_ROI_Y2.data <= self.SQM_ROI_Y1.data:
                self.SQM_ROI_Y2.errors.append('Y2 must be greater than Y1')
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


        # file transfer validation
        if not self.FILETRANSFER__HOST.data:
            if self.FILETRANSFER__UPLOAD_IMAGE.data:
                self.FILETRANSFER__UPLOAD_IMAGE.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_PANORAMA.data:
                self.FILETRANSFER__UPLOAD_PANORAMA.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_RAW.data:
                self.FILETRANSFER__UPLOAD_RAW.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_FITS.data:
                self.FILETRANSFER__UPLOAD_FITS.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_METADATA.data:
                self.FILETRANSFER__UPLOAD_METADATA.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_VIDEO.data:
                self.FILETRANSFER__UPLOAD_VIDEO.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_MINI_VIDEO.data:
                self.FILETRANSFER__UPLOAD_MINI_VIDEO.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_KEOGRAM.data:
                self.FILETRANSFER__UPLOAD_KEOGRAM.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_STARTRAIL.data:
                self.FILETRANSFER__UPLOAD_STARTRAIL.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_STARTRAIL_VIDEO.data:
                self.FILETRANSFER__UPLOAD_STARTRAIL_VIDEO.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_PANORAMA_VIDEO.data:
                self.FILETRANSFER__UPLOAD_PANORAMA_VIDEO.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_ENDOFNIGHT.data:
                self.FILETRANSFER__UPLOAD_ENDOFNIGHT.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_REALTIME_KEOGRAM.data:
                self.FILETRANSFER__UPLOAD_REALTIME_KEOGRAM.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_LATEST_IMAGE.data:
                self.FILETRANSFER__UPLOAD_LATEST_IMAGE.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_LATEST_PANORAMA.data:
                self.FILETRANSFER__UPLOAD_LATEST_PANORAMA.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_LATEST_RAW.data:
                self.FILETRANSFER__UPLOAD_LATEST_RAW.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_LATEST_VIDEO.data:
                self.FILETRANSFER__UPLOAD_LATEST_VIDEO.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False

            if self.FILETRANSFER__UPLOAD_DB_BACKUP.data:
                self.FILETRANSFER__UPLOAD_DB_BACKUP.errors.append('No file transfer host is configured')
                self.FILETRANSFER__HOST.errors.append('No file transfer host is configured')
                result = False


        # S3
        if self.S3UPLOAD__ENABLE.data:
            if self.S3UPLOAD__CLASSNAME.data == 'boto3_generic':
                if not self.S3UPLOAD__ENDPOINT_URL.data:
                    self.S3UPLOAD__ENDPOINT_URL.errors.append('Endpoint URL is required')
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

                except AttributeError as e:
                    self.FOCUSER__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.FOCUSER__CLASSNAME.data.startswith('motorkit_'):
                try:
                    from adafruit_motorkit import MotorKit  # noqa: F401

                    # only care about pin1
                    if self.FOCUSER__GPIO_PIN_1.data:
                        try:
                            getattr(MotorKit, self.FOCUSER__GPIO_PIN_1.data)
                        except AttributeError:
                            self.FOCUSER__GPIO_PIN_1.errors.append('PIN {0:s} not valid for your system (try stepper1, stepper2, etc)'.format(self.FOCUSER__GPIO_PIN_1.data))
                            result = False
                    else:
                        self.FOCUSER__GPIO_PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.FOCUSER__CLASSNAME.errors.append('motorkit python module not installed')
                    result = False
                except AttributeError as e:
                    self.FOCUSER__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
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

                except AttributeError as e:
                    self.DEW_HEATER__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.DEW_HEATER__CLASSNAME.data.startswith('rpigpio_'):
                try:
                    import RPi.GPIO  # noqa: F401

                    if self.DEW_HEATER__PIN_1.data:
                        try:
                            pin_int = int(self.DEW_HEATER__PIN_1.data)

                            if pin_int < 1:
                                self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                                result = False
                            elif pin_int > 40:
                                self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                                result = False
                        except ValueError:
                            self.DEW_HEATER__PIN_1.errors.append('PIN must be a number')
                            result = False

                    else:
                        self.DEW_HEATER__PIN_1.errors.append('PIN must be defined')
                        result = False
                except ImportError:
                    self.DEW_HEATER__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.DEW_HEATER__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False
                except RuntimeError as e:
                    self.DEW_HEATER__PIN_1.errors.append('RuntimeError: {0:s}'.format(str(e)))
                    result = False

            elif self.DEW_HEATER__CLASSNAME.data.startswith('gpiozero_'):
                try:
                    import gpiozero  # noqa: F401

                    if self.DEW_HEATER__PIN_1.data:
                        try:
                            pin_int = int(self.DEW_HEATER__PIN_1.data)

                            if pin_int < 1:
                                self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                                result = False
                            elif pin_int > 40:
                                self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                                result = False
                        except ValueError:
                            self.DEW_HEATER__PIN_1.errors.append('PIN must be a number')
                            result = False

                    else:
                        self.DEW_HEATER__PIN_1.errors.append('PIN must be defined')
                        result = False
                except ImportError:
                    self.DEW_HEATER__CLASSNAME.errors.append('gpiozero python module not installed')
                    result = False
                except PermissionError:
                    self.DEW_HEATER__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

            elif self.DEW_HEATER__CLASSNAME.data.startswith('motorkit_'):
                try:
                    from adafruit_motorkit import MotorKit  # noqa: F401,F811

                    if self.DEW_HEATER__PIN_1.data:
                        try:
                            getattr(MotorKit, self.DEW_HEATER__PIN_1.data)
                        except AttributeError:
                            self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system (try motor1, motor2, etc)'.format(self.DEW_HEATER__PIN_1.data))
                            result = False
                    else:
                        self.DEW_HEATER__PIN_1.errors.append('PIN must be defined')
                        result = False
                except ImportError:
                    self.DEW_HEATER__CLASSNAME.errors.append('motorkit python module not installed')
                    result = False
                except AttributeError as e:
                    self.DEW_HEATER__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.DEW_HEATER__CLASSNAME.data == 'dew_heater_dockerpi_4channel_relay':

                try:
                    import board
                except ImportError:
                    self.DEW_HEATER__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.DEW_HEATER__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


                try:
                    board.I2C()

                    from ..devices.controllers.dockerpi import DockerPi4ChannelRelay

                    if self.DEW_HEATER__PIN_1.data:
                        try:
                            board.I2C()
                            getattr(DockerPi4ChannelRelay, self.DEW_HEATER__PIN_1.data)
                        except AttributeError:
                            self.DEW_HEATER__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.DEW_HEATER__PIN_1.data))
                            result = False
                    else:
                        self.DEW_HEATER__PIN_1.errors.append('PIN must be defined')
                        result = False

                except AttributeError:
                    self.DEW_HEATER__CLASSNAME.errors.append('I2C not available for your system')
                    result = False


        try:
            if int(self.DEW_HEATER__THOLD_DIFF_HIGH.data) >= int(self.DEW_HEATER__THOLD_DIFF_MED.data):
                self.DEW_HEATER__THOLD_DIFF_HIGH.errors.append('HIGH must be less than MEDIUM')
                self.DEW_HEATER__THOLD_DIFF_MED.errors.append('MEDIUM must be greater than HIGH')
                result = False


            if int(self.DEW_HEATER__THOLD_DIFF_MED.data) >= int(self.DEW_HEATER__THOLD_DIFF_LOW.data):
                self.DEW_HEATER__THOLD_DIFF_MED.errors.append('MEDIUM must be less than LOW')
                self.DEW_HEATER__THOLD_DIFF_LOW.errors.append('LOW must be greater than MEDIUM')
                result = False
        except ValueError:
            # integer validation is caught later
            pass


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

                except AttributeError as e:
                    self.FAN__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.FAN__CLASSNAME.data.startswith('rpigpio_'):
                try:
                    import RPi.GPIO  # noqa: F401,F811

                    if self.FAN__PIN_1.data:
                        try:
                            pin_int = int(self.FAN__PIN_1.data)
                        except ValueError:
                            self.FAN__PIN_1.errors.append('PIN must be a number')
                            result = False

                        if pin_int < 1:
                            self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                            result = False
                        elif pin_int > 40:
                            self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                            result = False
                    else:
                        self.FAN__PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.FAN__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.FAN__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False
                except RuntimeError as e:
                    self.FAN__PIN_1.errors.append('RuntimeError: {0:s}'.format(str(e)))
                    result = False

            elif self.FAN__CLASSNAME.data.startswith('gpiozero_'):
                try:
                    import gpiozero  # noqa: F401,F811

                    if self.FAN__PIN_1.data:
                        try:
                            pin_int = int(self.FAN__PIN_1.data)

                            if pin_int < 1:
                                self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                                result = False
                            elif pin_int > 40:
                                self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                                result = False
                        except ValueError:
                            self.FAN__PIN_1.errors.append('PIN must be a number')
                            result = False

                    else:
                        self.FAN__PIN_1.errors.append('PIN must be defined')
                        result = False

                except ImportError:
                    self.FAN__CLASSNAME.errors.append('gpiozero python module not installed')
                    result = False
                except PermissionError:
                    self.FAN__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

            elif self.FAN__CLASSNAME.data.startswith('motorkit_'):
                try:
                    from adafruit_motorkit import MotorKit  # noqa: F401,F811

                    if self.FAN__PIN_1.data:
                        try:
                            getattr(MotorKit, self.FAN__PIN_1.data)
                        except AttributeError:
                            self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system (try motor1, motor2, etc)'.format(self.FAN__PIN_1.data))
                            result = False
                    else:
                        self.FAN__PIN_1.errors.append('PIN must be defined')
                        result = False
                except ImportError:
                    self.FAN__CLASSNAME.errors.append('motorkit python module not installed')
                    result = False
                except AttributeError as e:
                    self.FAN__CLASSNAME.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.FAN__CLASSNAME.data == 'fan_dockerpi_4channel_relay':

                try:
                    import board
                except ImportError:
                    self.FAN__CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.FAN__PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


                try:
                    board.I2C()

                    from ..devices.controllers.dockerpi import DockerPi4ChannelRelay

                    if self.FAN__PIN_1.data:
                        try:
                            board.I2C()
                            getattr(DockerPi4ChannelRelay, self.FAN__PIN_1.data)
                        except AttributeError:
                            self.FAN__PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.FAN__PIN_1.data))
                            result = False
                    else:
                        self.FAN__PIN_1.errors.append('PIN must be defined')
                        result = False

                except AttributeError:
                    self.FAN__CLASSNAME.errors.append('I2C not available for your system')
                    result = False


        try:
            if int(self.FAN__THOLD_DIFF_HIGH.data) <= int(self.FAN__THOLD_DIFF_MED.data):
                self.FAN__THOLD_DIFF_HIGH.errors.append('HIGH must be greater than MEDIUM')
                self.FAN__THOLD_DIFF_MED.errors.append('MEDIUM must be less than HIGH')
                result = False

            if int(self.FAN__THOLD_DIFF_MED.data) <= int(self.FAN__THOLD_DIFF_LOW.data):
                self.FAN__THOLD_DIFF_MED.errors.append('MEDIUM must be greater than LOW')
                self.FAN__THOLD_DIFF_LOW.errors.append('LOW must be less than MEDIUM')
                result = False
        except ValueError:
            # integer validation is caught later
            pass


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

            elif self.GENERIC_GPIO__A_CLASSNAME.data == 'gpio_dockerpi_4channel_relay':

                try:
                    import board
                except ImportError:
                    self.GENERIC_GPIO__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.GENERIC_GPIO__A_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False


                try:
                    board.I2C()

                    from ..devices.controllers.dockerpi import DockerPi4ChannelRelay

                    if self.GENERIC_GPIO__A_PIN_1.data:
                        try:
                            board.I2C()
                            getattr(DockerPi4ChannelRelay, self.GENERIC_GPIO__A_PIN_1.data)
                        except AttributeError:
                            self.GENERIC_GPIO__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.GENERIC_GPIO__A_PIN_1.data))
                            result = False
                    else:
                        self.GENERIC_GPIO__A_PIN_1.errors.append('PIN must be defined')
                        result = False

                except AttributeError:
                    self.GENERIC_GPIO__A_CLASSNAME.errors.append('I2C not available for your system')
                    result = False

        # manual gpio
        if self.MANUAL_GPIO__A_CLASSNAME.data:
            if self.MANUAL_GPIO__A_CLASSNAME.data.startswith('rpigpio_'):
                try:
                    import RPi.GPIO  # noqa: F401, F811

                    if self.MANUAL_GPIO__A_PIN_1.data:
                        try:
                            pin_int = int(self.MANUAL_GPIO__A_PIN_1.data)

                            if pin_int < 1:
                                self.MANUAL_GPIO__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_1.data))
                                result = False
                            elif pin_int > 40:
                                self.MANUAL_GPIO__A_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_1.data))
                                result = False
                        except ValueError:
                            self.MANUAL_GPIO__A_PIN_1.errors.append('PIN must be a number')
                            result = False
                    else:
                        self.MANUAL_GPIO__A_PIN_1.errors.append('PIN must be defined')
                        result = False


                    if self.MANUAL_GPIO__A_PIN_2.data:
                        try:
                            pin_int = int(self.MANUAL_GPIO__A_PIN_2.data)

                            if pin_int < 1:
                                self.MANUAL_GPIO__A_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_2.data))
                                result = False
                            elif pin_int > 40:
                                self.MANUAL_GPIO__A_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_2.data))
                                result = False
                        except ValueError:
                            self.MANUAL_GPIO__A_PIN_2.errors.append('PIN must be a number')
                            result = False
                    else:
                        self.MANUAL_GPIO__A_PIN_2.errors.append('PIN must be defined')
                        result = False


                    if self.MANUAL_GPIO__A_PIN_3.data:
                        try:
                            pin_int = int(self.MANUAL_GPIO__A_PIN_3.data)

                            if pin_int < 1:
                                self.MANUAL_GPIO__A_PIN_3.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_3.data))
                                result = False
                            elif pin_int > 40:
                                self.MANUAL_GPIO__A_PIN_3.errors.append('PIN {0:s} not valid for your system'.format(self.MANUAL_GPIO__A_PIN_3.data))
                                result = False
                        except ValueError:
                            self.MANUAL_GPIO__A_PIN_3.errors.append('PIN must be a number')
                            result = False
                    else:
                        self.MANUAL_GPIO__A_PIN_3.errors.append('PIN must be defined')
                        result = False
                except ImportError:
                    self.MANUAL_GPIO__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False
                except PermissionError:
                    self.MANUAL_GPIO__A_CLASSNAME.errors.append('GPIO permissions need to be fixed')
                    result = False
                except RuntimeError as e:
                    self.MANUAL_GPIO__A_CLASSNAME.errors.append('RuntimeError: {0:s}'.format(str(e)))
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

                    if self.TEMP_SENSOR__A_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__A_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__A_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__A_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__A_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__A_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
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

                    if self.TEMP_SENSOR__A_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__A_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__A_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__A_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__A_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__A_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401
                except ImportError:
                    self.TEMP_SENSOR__A_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__A_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__A_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__A_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__A_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__A_PIN_1.errors.append('Topics must be defined')
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

                    if self.TEMP_SENSOR__B_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__B_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__B_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__B_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__B_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__B_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
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

                    if self.TEMP_SENSOR__B_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__B_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__B_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__B_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__B_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__B_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401,F811
                except ImportError:
                    self.TEMP_SENSOR__B_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__B_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__B_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__B_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__B_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__B_PIN_1.errors.append('Topics must be defined')
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

                    if self.TEMP_SENSOR__C_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__C_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__C_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__C_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__C_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__C_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
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

                    if self.TEMP_SENSOR__C_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__C_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__C_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__C_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__C_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__C_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401,F811
                except ImportError:
                    self.TEMP_SENSOR__C_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__C_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__C_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__C_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__C_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__C_PIN_1.errors.append('Topics must be defined')
                    result = False


        # sensor D
        if self.TEMP_SENSOR__D_CLASSNAME.data:
            if self.TEMP_SENSOR__D_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__D_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__D_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__D_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__D_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__D_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__D_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__D_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__D_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__D_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__D_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__D_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__D_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__D_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__D_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__D_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__D_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__D_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__D_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__D_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__D_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__D_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__D_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__D_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__D_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__D_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__D_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401,F811
                except ImportError:
                    self.TEMP_SENSOR__D_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__D_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__D_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__D_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__D_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__D_PIN_1.errors.append('Topics must be defined')
                    result = False


        # sensor E
        if self.TEMP_SENSOR__E_CLASSNAME.data:
            if self.TEMP_SENSOR__E_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__E_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__E_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__E_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__E_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__E_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__E_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__E_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__E_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__E_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__E_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__E_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__E_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__E_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__E_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__E_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__E_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__E_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__E_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__E_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__E_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__E_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__E_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__E_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__E_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__E_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__E_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401,F811
                except ImportError:
                    self.TEMP_SENSOR__E_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__E_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__E_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__E_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__E_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__E_PIN_1.errors.append('Topics must be defined')
                    result = False


        # sensor F
        if self.TEMP_SENSOR__F_CLASSNAME.data:
            if self.TEMP_SENSOR__F_CLASSNAME.data.startswith('blinka_'):
                try:
                    import board

                    if self.TEMP_SENSOR__F_PIN_1.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__F_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__F_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__F_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__F_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__F_PIN_2.data:
                        try:
                            getattr(board, self.TEMP_SENSOR__F_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__F_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__F_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except NotImplementedError:
                    self.TEMP_SENSOR__F_CLASSNAME.errors.append('System not suppored by Adafruit Blinka module')
                    result = False

                except ImportError:
                    self.TEMP_SENSOR__F_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except PermissionError:
                    self.TEMP_SENSOR__F_PIN_1.errors.append('GPIO permissions need to be fixed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__F_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__F_CLASSNAME.data.startswith('cpads_'):
                try:
                    import adafruit_ads1x15.ads1115 as ADS

                    if self.TEMP_SENSOR__F_PIN_1.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__F_PIN_1.data)
                        except AttributeError:
                            self.TEMP_SENSOR__F_PIN_1.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__F_PIN_1.data))
                            result = False
                    else:
                        self.TEMP_SENSOR__F_PIN_1.errors.append('PIN must be defined')
                        result = False

                    if self.TEMP_SENSOR__F_PIN_2.data:
                        try:
                            getattr(ADS, self.TEMP_SENSOR__F_PIN_2.data)
                        except AttributeError:
                            self.TEMP_SENSOR__F_PIN_2.errors.append('PIN {0:s} not valid for your system'.format(self.TEMP_SENSOR__F_PIN_2.data))
                            result = False
                    else:
                        # permit empty pin 2
                        pass

                except ImportError:
                    self.TEMP_SENSOR__F_CLASSNAME.errors.append('GPIO python modules not installed')
                    result = False

                except AttributeError as e:
                    self.TEMP_SENSOR__F_PIN_1.errors.append('AttributeError: {0:s}'.format(str(e)))
                    result = False

            elif self.TEMP_SENSOR__F_CLASSNAME.data.startswith('qwiic_'):
                try:
                    import qwiic_i2c  # noqa: F401,F811
                except ImportError:
                    self.TEMP_SENSOR__F_CLASSNAME.errors.append('SparkFun QWIIC modules not installed')
                    result = False

            elif self.TEMP_SENSOR__F_CLASSNAME.data.startswith('mqtt_broker_'):
                if self.TEMP_SENSOR__F_PIN_1.data:
                    topic_list = self.TEMP_SENSOR__F_PIN_1.data.split(',')

                    if len(topic_list) != len(set(topic_list)):
                        self.TEMP_SENSOR__F_PIN_1.errors.append('Contains duplicate topics')
                        result = False
                else:
                    self.TEMP_SENSOR__F_PIN_1.errors.append('Topics must be defined')
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



        from ..devices import sensors as indi_allsky_sensors

        check_sensor_slots = list()

        if self.TEMP_SENSOR__A_CLASSNAME.data:
            temp_sensor__a_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__A_CLASSNAME.data)
            temp_sensor__a_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__A_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name'   : 'Sensor A',
                #'class'  : temp_sensor__a_class,
                'slot'   : self.TEMP_SENSOR__A_USER_VAR_SLOT,
                'set'    : set(range(temp_sensor__a_slot_int, temp_sensor__a_slot_int + temp_sensor__a_class.METADATA['count'])),
            })

        if self.TEMP_SENSOR__B_CLASSNAME.data:
            temp_sensor__b_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__B_CLASSNAME.data)
            temp_sensor__b_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__B_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name' : 'Sensor B',
                #'class' : temp_sensor__b_class,
                'slot'  : self.TEMP_SENSOR__B_USER_VAR_SLOT,
                'set'   : set(range(temp_sensor__b_slot_int, temp_sensor__b_slot_int + temp_sensor__b_class.METADATA['count'])),
            })

        if self.TEMP_SENSOR__C_CLASSNAME.data:
            temp_sensor__c_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__C_CLASSNAME.data)
            temp_sensor__c_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__C_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name' : 'Sensor C',
                #'class' : temp_sensor__c_class,
                'slot'  : self.TEMP_SENSOR__C_USER_VAR_SLOT,
                'set'   : set(range(temp_sensor__c_slot_int, temp_sensor__c_slot_int + temp_sensor__c_class.METADATA['count'])),
            })

        if self.TEMP_SENSOR__D_CLASSNAME.data:
            temp_sensor__d_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__D_CLASSNAME.data)
            temp_sensor__d_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__D_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name' : 'Sensor D',
                #'class' : temp_sensor__d_class,
                'slot'  : self.TEMP_SENSOR__D_USER_VAR_SLOT,
                'set'   : set(range(temp_sensor__d_slot_int, temp_sensor__d_slot_int + temp_sensor__d_class.METADATA['count'])),
            })

        if self.TEMP_SENSOR__E_CLASSNAME.data:
            temp_sensor__e_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__E_CLASSNAME.data)
            temp_sensor__e_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__E_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name' : 'Sensor E',
                #'class' : temp_sensor__e_class,
                'slot'  : self.TEMP_SENSOR__E_USER_VAR_SLOT,
                'set'   : set(range(temp_sensor__e_slot_int, temp_sensor__e_slot_int + temp_sensor__e_class.METADATA['count'])),
            })

        if self.TEMP_SENSOR__F_CLASSNAME.data:
            temp_sensor__f_class = getattr(indi_allsky_sensors, self.TEMP_SENSOR__F_CLASSNAME.data)
            temp_sensor__f_slot_int = constants.SENSOR_INDEX_MAP[self.TEMP_SENSOR__F_USER_VAR_SLOT.data]
            check_sensor_slots.append({
                'name' : 'Sensor F',
                #'class' : temp_sensor__f_class,
                'slot'  : self.TEMP_SENSOR__F_USER_VAR_SLOT,
                'set'   : set(range(temp_sensor__f_slot_int, temp_sensor__f_slot_int + temp_sensor__f_class.METADATA['count'])),
            })



        for slot1, slot2 in itertools.combinations(check_sensor_slots, 2):
            if not slot1['set'].isdisjoint(slot2['set']):
                slot1['slot'].errors.append('Overlapping slots with {0:s}'.format(slot2['name']))
                slot2['slot'].errors.append('Overlapping slots with {0:s}'.format(slot1['name']))
                result = False


        for slot in check_sensor_slots:
            if list(slot['set'])[-1] > 59:
                slot['slot'].errors.append('Not enough sensor slots to fit all values')
                result = False


        if self.DEW_HEATER__THOLD_ENABLE.data:
            if self.DEW_HEATER__TEMP_USER_VAR_SLOT.data == self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.data:
                self.DEW_HEATER__TEMP_USER_VAR_SLOT.errors.append('Sensor same as dew point')
                self.DEW_HEATER__DEWPOINT_USER_VAR_SLOT.errors.append('Sensor same as temperature')
                result = False


        return result


