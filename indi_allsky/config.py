import sys
import os
import time
from datetime import datetime
from datetime import timezone
import io
import json
import tempfile
import random
from pathlib import Path
from collections import OrderedDict
from prettytable import PrettyTable
import logging

from cryptography.fernet import Fernet
#from cryptography.fernet import InvalidToken

from .flask.models import IndiAllSkyDbConfigTable
from .flask.models import IndiAllSkyDbUserTable

from .flask import create_app
from .flask import db

from sqlalchemy.orm.exc import NoResultFound

from .version import __config_level__


app = create_app()

logger = logging.getLogger('indi_allsky')


class IndiAllSkyConfigBase(object):

    _base_config = OrderedDict({
        "ENCRYPT_PASSWORDS_comment" : "Do not manually adjust",
        "ENCRYPT_PASSWORDS" : False,
        "CAMERA_INTERFACE" : "indi",
        "INDI_SERVER" : "localhost",
        "INDI_PORT"   : 7624,
        "INDI_CAMERA_NAME" : "",
        "OWNER" : "",
        "LENS_NAME" : "AllSky Lens",
        "LENS_FOCAL_LENGTH" : 2.5,
        "LENS_FOCAL_RATIO"  : 2.0,
        "LENS_IMAGE_CIRCLE" : 3000,
        "LENS_OFFSET_X"     : 0,
        "LENS_OFFSET_Y"     : 0,
        "LENS_ALTITUDE"     : 90.0,
        "LENS_AZIMUTH"      : 0.0,
        "CCD_CONFIG" : {
            "NIGHT" : {
                "GAIN"    : 100,
                "BINNING" : 1,
            },
            "MOONMODE" : {
                "GAIN"    : 75,
                "BINNING" : 1,
            },
            "DAY" : {
                "GAIN"    : 0,
                "BINNING" : 1,
            }
        },
        "INDI_CONFIG_DEFAULTS" : {
            "SWITCHES" : {},
            "PROPERTIES" : {},
            "TEXT" : {},
        },
        "INDI_CONFIG_DAY" : {},
        "CCD_EXPOSURE_MAX"     : 15.00000,
        "CCD_EXPOSURE_DEF"     : 0.0,
        "CCD_EXPOSURE_MIN"     : 0.0,
        "CCD_EXPOSURE_MIN_DAY" : 0.0,
        "CCD_BIT_DEPTH"        : 0,  # 0 is auto
        "EXPOSURE_PERIOD"      : 15.00000,
        "EXPOSURE_PERIOD_DAY"  : 15.00000,
        "FOCUS_MODE"           : False,
        "FOCUS_DELAY"          : 4.0,
        "CFA_PATTERN"      : "",  # None, GRBG, RGGB, BGGR, GBRG
        "USE_NIGHT_COLOR"  : True,
        "SCNR_ALGORITHM"   : "",  # empty string, average_neutral, or maximum_neutral
        "SCNR_ALGORITHM_DAY" : "",
        "WBR_FACTOR"       : 1.0,
        "WBG_FACTOR"       : 1.0,
        "WBB_FACTOR"       : 1.0,
        "WBR_FACTOR_DAY"   : 1.0,
        "WBG_FACTOR_DAY"   : 1.0,
        "WBB_FACTOR_DAY"   : 1.0,
        "AUTO_WB"          : False,
        "AUTO_WB_DAY"      : False,
        "SATURATION_FACTOR"     : 1.0,
        "SATURATION_FACTOR_DAY" : 1.0,
        "GAMMA_CORRECTION"      : 1.0,
        "GAMMA_CORRECTION_DAY"  : 1.0,
        "CCD_COOLING"      : False,
        "CCD_TEMP"         : 15.0,
        "TEMP_DISPLAY"     : "c",  # c = celsius, f = fahrenheit, k = kelvin",
        "PRESSURE_DISPLAY" : "hPa",  # hPa = hectoPascals/millibars, psi = psi, inHg = inches of mercury, mmHg = mm of mercury
        "WINDSPEED_DISPLAY": "ms",  # ms = meters/s, mph = miles/hour, knots = knots, kph = km/hour
        "CCD_TEMP_SCRIPT"  : "",
        "GPS_ENABLE"       : False,
        "TARGET_ADU"         : 75,
        "TARGET_ADU_DAY"     : 75,
        "TARGET_ADU_DEV"     : 10,
        "TARGET_ADU_DEV_DAY" : 20,
        "ADU_ROI" : [],
        "ADU_FOV_DIV" : 4,
        "DETECT_STARS" : True,
        "DETECT_STARS_THOLD" : 0.6,
        "DETECT_METEORS" : False,
        "DETECT_MASK" : "",
        "DETECT_DRAW" : False,
        "LOGO_OVERLAY" : "",
        "SQM_ROI" : [],
        "SQM_FOV_DIV" : 4,
        "LOCATION_NAME"      : "",
        "LOCATION_LATITUDE"  : 33.0,
        "LOCATION_LONGITUDE" : -84.0,
        "LOCATION_ELEVATION" : 300.0,
        "CAPTURE_PAUSE"            : False,
        "TIMELAPSE_ENABLE"         : True,
        "TIMELAPSE_SKIP_FRAMES"    : 4,
        "TIMELAPSE" : {
            "PRE_PROCESSOR"  : "standard",
            "IMAGE_CIRCLE"   : 2000,
            "KEOGRAM_RATIO"  : 0.15,
            "PRE_SCALE"      : 50,
            "FFMPEG_REPORT"  : False,
        },
        "DAYTIME_CAPTURE"          : True,
        "DAYTIME_CAPTURE_SAVE"     : True,
        "DAYTIME_TIMELAPSE"        : True,
        "DAYTIME_CONTRAST_ENHANCE" : False,
        "NIGHT_CONTRAST_ENHANCE"   : False,
        "CONTRAST_ENHANCE_16BIT"   : False,
        "CLAHE_CLIPLIMIT"          : 3.0,
        "CLAHE_GRIDSIZE"           : 8,
        "NIGHT_SUN_ALT_DEG"        : -6.0,
        "NIGHT_MOONMODE_ALT_DEG"   : 0,
        "NIGHT_MOONMODE_PHASE"     : 33,
        "WEB_NONLOCAL_IMAGES"      : False,
        "WEB_LOCAL_IMAGES_ADMIN"   : False,
        "WEB_EXTRA_TEXT"           : "",
        "WEB_STATUS_TEMPLATE"      : "Status: {status:s}\nLat: {latitude:0.1f}/Long: {longitude:0.1f}\nSidereal: {sidereal_time:s}\nMode: {mode:s}\nNext change: {mode_next_change:s} [{mode_next_change_h:0.1f}h]\nSun: {sun_alt:0.1f}&deg; {sun_dir:s}\nMoon: {moon_alt:0.1f}&deg; {moon_dir:s}\nRise: {moon_next_rise:s} [{moon_next_rise_h:0.1f}h]\nSet: {moon_next_set:s} [{moon_next_set_h:0.1f}h]\nPhase: {moon_phase_str:s} <span data-bs-toggle=\"tooltip\" data-bs-placement=\"right\" title=\"{moon_phase:0.0f}%\">{moon_glyph:s}</span>\nSmoke: {smoke_rating:s} {smoke_rating_status}\nKp-index: {kpindex:0.2f} {kpindex_rating:s} {kpindex_trend:s} {kpindex_status:s}\nAurora: {ovation_max:d}% {ovation_max_status}",
        "HEALTHCHECK" : {
            "DISK_USAGE"     : 90.0,
            "SWAP_USAGE"     : 90.0,
        },
        "IMAGE_STRETCH" : {
            "CLASSNAME"         : "",
            "MODE1_GAMMA"       : 3.0,
            "MODE1_STDDEVS"     : 2.25,
            "MODE2_SHADOWS"     : 0.0,
            "MODE2_MIDTONES"    : 0.35,
            "MODE2_HIGHLIGHTS"  : 1.0,
            "SPLIT"             : False,
            "MOONMODE"          : False,
            "DAYTIME"           : False,
        },
        "KEOGRAM_ANGLE"         : 0,
        "KEOGRAM_H_SCALE"       : 100,
        "KEOGRAM_V_SCALE"       : 33,
        "KEOGRAM_CROP_TOP"      : 0,  # percent
        "KEOGRAM_CROP_BOTTOM"   : 0,  # percent
        "KEOGRAM_LABEL"         : True,
        "LONGTERM_KEOGRAM"      : {
            "ENABLE"        : True,
            "OFFSET_X"      : 0,
            "OFFSET_Y"      : 0,
        },
        "REALTIME_KEOGRAM" : {
            "MAX_ENTRIES"   : 1000,
            "SAVE_INTERVAL" : 25,
        },
        "STARTRAILS_MAX_ADU"    : 65,
        "STARTRAILS_MASK_THOLD" : 190,
        "STARTRAILS_PIXEL_THOLD": 1.0,
        "STARTRAILS_MIN_STARS"  : 0,
        "STARTRAILS_TIMELAPSE"  : True,
        "STARTRAILS_TIMELAPSE_MINFRAMES" : 250,
        "STARTRAILS_SUN_ALT_THOLD"       : -15.0,
        "STARTRAILS_MOONMODE_THOLD"      : True,
        "STARTRAILS_MOON_ALT_THOLD"      : 91.0,
        "STARTRAILS_MOON_PHASE_THOLD"    : 101.0,
        "STARTRAILS_USE_DB_DATA"         : True,
        "IMAGE_CALIBRATE_DARK"  : True,
        "IMAGE_CALIBRATE_BPM"   : False,
        "IMAGE_EXIF_PRIVACY"    : False,
        "IMAGE_FILE_TYPE" : "jpg",  # jpg, png, or tif
        "IMAGE_FILE_COMPRESSION" : {
            "jpg"   : 90,
            "png"   : 5,
            "tif"   : 5,  # 5 = LZW
        },
        "IMAGE_FOLDER"     : "/var/www/html/allsky/images",
        "IMAGE_LABEL_TEMPLATE": "# size:30 [Use 60 for higher resolution cameras]\n# xy:-15,15 (Upper Right)\n# anchor:ra (Right Justified)\n# color:150,0,0\n{timestamp:%Y.%m.%d %H:%M:%S}\n# color:100,100,0\nLat {latitude:0.0f} Long {longitude:0.0f}\n# color:150,150,150\nTiangong {tiangong_up:s} [{tiangong_next_h:0.1f}h/{tiangong_next_alt:0.0f}\u00b0]\nHubble {hst_up:s} [{hst_next_h:0.1f}h/{hst_next_alt:0.0f}\u00b0]\nISS {iss_up:s} [{iss_next_h:0.1f}h/{iss_next_alt:0.0f}\u00b0]\n# xy:-15,-240 (Lower Right) [Use -15,-450 for size 60]\n# color:175,175,0\nSun {sun_alt:0.0f}\u00b0\n# color:125,0,0\nMercury {mercury_alt:0.0f}\u00b0\n# color:100,150,150\nVenus {venus_alt:0.0f}\u00b0\n# color:150,0,0\nMars {mars_alt:0.0f}\u00b0\n# color:100,100,0\nJupiter {jupiter_alt:0.0f}\u00b0\n# color:100,100,150\nSaturn {saturn_alt:0.0f}\u00b0\n# color:150,150,150\nMoon {moon_phase:0.0f}% {moon_alt:0.0f}\u00b0\n# xy:15,-120 (Lower Left)  [Use 15,-210 for size 60]\n# anchor:la (Left Justified)\n# color:0,150,150\nStars {stars:d}\n# color:150,50,50\nKp-index {kpindex:0.2f}\n# color:150,150,150\nSmoke {smoke_rating:s}\n# xy:15,15 (Upper Left)\n# color:0,150,0\nExposure {exposure:0.6f}\n# color:150,50,0\nGain {gain:d}\n# color:50,50,150\nCamera {temp:0.1f}\u00b0{temp_unit:s}\n# color:150,0,150\nStretch {stretch:s}\nStacking {stack_method:s}\n# color:200,200,200 (default color)\n# additional labels will be added here",
        "URL_TEMPLATE": "https://{bucket}.s3.{region}.{host}",
        "IMAGE_EXTRA_TEXT" : "",
        "IMAGE_CROP_ROI"   : [],
        "IMAGE_ROTATE"     : "",  # empty, ROTATE_90_CLOCKWISE, ROTATE_90_COUNTERCLOCKWISE, ROTATE_180
        "IMAGE_ROTATE_ANGLE" : 0,
        "IMAGE_ROTATE_KEEP_SIZE"   : False,
        #"IMAGE_ROTATE_WITH_OFFSET" : False,
        "IMAGE_FLIP_V"     : True,
        "IMAGE_FLIP_H"     : True,
        "IMAGE_SCALE"      : 100,
        "NIGHT_GRAYSCALE"  : False,
        "DAYTIME_GRAYSCALE": False,
        "MOON_OVERLAY" : {
            "ENABLE"   : True,
            "X"        : -500,
            "Y"        : -200,
            "SCALE"    : 0.5,
            "DARK_SIDE_SCALE" : 0.4,
            "FLIP_H"   : False,
            "FLIP_V"   : False,
        },
        "LIGHTGRAPH_OVERLAY" : {
            "ENABLE"        : False,
            "GRAPH_HEIGHT"  : 30,
            "GRAPH_BORDER"  : 3,
            "NOW_MARKER_SIZE" : 8,
            "Y"             : 10,
            "OFFSET_X"      : 0,
            "SCALE"         : 1.0,
            "LABEL"         : True,
            "HOUR_LINES"    : True,
            "DAY_COLOR"     : [150, 150, 150],
            "DUSK_COLOR"    : [200, 100, 60],
            "NIGHT_COLOR"   : [30, 30, 30],
            "HOUR_COLOR"    : [100, 15, 15],
            "BORDER_COLOR"  : [1, 1, 1],
            "NOW_COLOR"     : [120, 120, 200],
            "FONT_COLOR"    : [150, 150, 150],
            "OPACITY"       : 100,
            "PIL_FONT_SIZE" : 20,
            "OPENCV_FONT_SCALE" : 0.5,
        },
        "IMAGE_CIRCLE_MASK" : {
            "ENABLE"   : False,
            "DIAMETER" : 3000,
            "OFFSET_X" : 0,
            "OFFSET_Y" : 0,
            "BLUR"     : 35,
            "OPACITY"  : 100,
            "OUTLINE"  : False,
        },
        "FISH2PANO" : {
            "ENABLE"   : False,
            "DIAMETER" : 3000,
            "OFFSET_X" : 0,
            "OFFSET_Y" : 0,
            "ROTATE_ANGLE" : -90,
            "SCALE"    : 0.5,
            "MODULUS"  : 2,
            "FLIP_H"   : False,
            "ENABLE_CARDINAL_DIRS" : True,
            "DIRS_OFFSET_BOTTOM"   : 25,
            "OPENCV_FONT_SCALE"    : 0.8,
            "PIL_FONT_SIZE"        : 30,
        },
        "IMAGE_SAVE_FITS"     : False,
        "IMAGE_SAVE_FITS_PRE_DARK" : False,
        "IMAGE_EXPORT_RAW"    : "",  # png or tif (or empty)
        "IMAGE_EXPORT_FOLDER" : "/var/www/html/allsky/images/export",
        "IMAGE_EXPORT_FLIP_V" : False,
        "IMAGE_EXPORT_FLIP_H" : False,
        "IMAGE_STACK_METHOD"  : "maximum",  # maximum, average, or minimum
        "IMAGE_STACK_COUNT"   : 1,
        "IMAGE_STACK_ALIGN"   : False,
        "IMAGE_ALIGN_DETECTSIGMA" : 5,
        "IMAGE_ALIGN_POINTS" : 50,
        "IMAGE_ALIGN_SOURCEMINAREA" : 10,
        "IMAGE_STACK_SPLIT"   : False,
        "THUMBNAILS" : {
            "IMAGES_AUTO" : True,
        },
        "IMAGE_EXPIRE_DAYS"     : 10,
        "IMAGE_RAW_EXPIRE_DAYS" : 10,
        "IMAGE_FITS_EXPIRE_DAYS": 10,
        "TIMELAPSE_EXPIRE_DAYS" : 365,
        "TIMELAPSE_OVERWRITE"   : False,
        "IMAGE_QUEUE_MAX"       : 3,
        "IMAGE_QUEUE_MIN"       : 1,
        "IMAGE_QUEUE_BACKOFF"   : 0.5,
        "FFMPEG_FRAMERATE" : 25,
        "FFMPEG_BITRATE"   : "5000k",
        "FFMPEG_VFSCALE"   : "",
        "FFMPEG_CODEC"     : "libx264",
        "FFMPEG_EXTRA_OPTIONS" : "-level 3.1",
        "FITSHEADERS" : [
            [ "INSTRUME", "indi-allsky" ],
            [ "OBSERVER", "" ],
            [ "SITE", "" ],
            [ "OBJECT", "" ],
            [ "NOTES", "" ],
        ],
        "IMAGE_LABEL_SYSTEM" : "pillow",
        "TEXT_PROPERTIES" : {
            "DATE_FORMAT"    : "%Y%m%d %H:%M:%S",
            "FONT_FACE"      : "FONT_HERSHEY_SIMPLEX",
            "FONT_AA"        : "LINE_AA",
            "FONT_SCALE"     : 0.8,
            "FONT_THICKNESS" : 1,
            "FONT_OUTLINE"   : True,
            "FONT_HEIGHT"    : 30,
            "FONT_X"         : 30,
            "FONT_Y"         : 30,
            "FONT_COLOR"     : [200, 200, 200],
            "PIL_FONT_FILE"  : "fonts-freefont-ttf/FreeMonoBold.ttf",
            "PIL_FONT_CUSTOM": "",
            "PIL_FONT_SIZE"  : 30,
        },
        "CARDINAL_DIRS" : {
            "ENABLE"         : True,
            "FONT_COLOR"     : [255, 0, 0],
            "SWAP_NS"        : False,
            "SWAP_EW"        : False,
            "CHAR_NORTH"     : "N",
            "CHAR_EAST"      : "E",
            "CHAR_WEST"      : "W",
            "CHAR_SOUTH"     : "S",
            "DIAMETER"       : 3000,
            "OFFSET_X"       : 0,
            "OFFSET_Y"       : 0,
            "OFFSET_TOP"     : 15,
            "OFFSET_LEFT"    : 15,
            "OFFSET_RIGHT"   : 15,
            "OFFSET_BOTTOM"  : 15,
            "OPENCV_FONT_SCALE" : 0.5,
            "PIL_FONT_SIZE"  : 20,
            "OUTLINE_CIRCLE" : False,
        },
        "ORB_PROPERTIES" : {
            "MODE"           : "ha",  # ha = hour angle, az = azimuth, alt = altitude, off = off
            "RADIUS"         : 9,
            "SUN_COLOR"      : [200, 200, 0],
            "MOON_COLOR"     : [128, 128, 128],
            "AZ_OFFSET"      : 0.0,
            "RETROGRADE"     : False,
        },
        "IMAGE_BORDER" : {
            "TOP"       : 0,
            "LEFT"      : 0,
            "RIGHT"     : 0,
            "BOTTOM"    : 0,
            "COLOR"     : [0, 0, 0],
        },
        "UPLOAD_WORKERS" : 2,
        "FILETRANSFER" : {
            "CLASSNAME"              : "pycurl_sftp",  # pycurl_sftp, pycurl_ftps, pycurl_ftpes, paramiko_sftp, python_ftp, python_ftpes
            "HOST"                   : "",
            "PORT"                   : 0,
            "USERNAME"               : "",
            "PASSWORD"               : "",
            "PASSWORD_E"             : "",
            "PRIVATE_KEY"            : "",
            "PUBLIC_KEY"             : "",
            "CONNECT_TIMEOUT"        : 10.0,
            "TIMEOUT"                : 60.0,
            "CERT_BYPASS"            : True,
            "ATOMIC_TRANSFERS"       : False,
            "REMOTE_IMAGE_NAME"          : "image_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}.{ext}",
            "REMOTE_IMAGE_FOLDER"        : "/home/allsky/upload/allsky/images/{day_date:%Y%m%d}/{timeofday:s}/{ts:%H}",
            "REMOTE_PANORAMA_NAME"       : "panorama_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}.{ext}",
            "REMOTE_PANORAMA_FOLDER"     : "/home/allsky/upload/allsky/panoramas/{day_date:%Y%m%d}/{timeofday:s}/{ts:%H}",
            "REMOTE_RAW_NAME"            : "raw_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}.{ext}",
            "REMOTE_RAW_FOLDER"          : "/home/allsky/upload/allsky/export/{day_date:%Y%m%d}/{timeofday:s}/{ts:%H}",
            "REMOTE_FITS_NAME"           : "image_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}.{ext}",
            "REMOTE_FITS_FOLDER"         : "/home/allsky/upload/allsky/fits/{day_date:%Y%m%d}/{timeofday:s}/{ts:%H}",
            "REMOTE_METADATA_NAME"       : "latest_metadata.json",
            "REMOTE_METADATA_FOLDER"     : "/home/allsky/upload/allsky",
            "REMOTE_VIDEO_NAME"          : "allsky-timelapse_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_VIDEO_FOLDER"        : "/home/allsky/upload/allsky/videos/{day_date:%Y%m%d}",
            "REMOTE_MINI_VIDEO_NAME"     : "allsky-minitimelapse_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_MINI_VIDEO_FOLDER"   : "/home/allsky/upload/allsky/videos/{day_date:%Y%m%d}",
            "REMOTE_KEOGRAM_NAME"        : "allsky-keogram_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_KEOGRAM_FOLDER"      : "/home/allsky/upload/allsky/keograms/{day_date:%Y%m%d}",
            "REMOTE_STARTRAIL_NAME"      : "allsky-startrail_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_STARTRAIL_FOLDER"    : "/home/allsky/upload/allsky/startrails/{day_date:%Y%m%d}",
            "REMOTE_STARTRAIL_VIDEO_NAME": "allsky-startrail_timelapse_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_STARTRAIL_VIDEO_FOLDER" : "/home/allsky/upload/allsky/videos/{day_date:%Y%m%d}",
            "REMOTE_PANORAMA_VIDEO_NAME" : "allsky-panorama_timelapse_ccd{camera_id:d}_{ts:%Y%m%d_%H%M%S}_{timeofday:s}.{ext}",
            "REMOTE_PANORAMA_VIDEO_FOLDER"  : "/home/allsky/upload/allsky/videos/{day_date:%Y%m%d}",
            "REMOTE_ENDOFNIGHT_FOLDER"   : "/home/allsky/upload/allsky",
            "UPLOAD_IMAGE"           : 0,
            "UPLOAD_PANORAMA"        : 0,
            "UPLOAD_RAW"             : False,
            "UPLOAD_FITS"            : False,
            "UPLOAD_METADATA"        : False,
            "UPLOAD_VIDEO"           : False,
            "UPLOAD_MINI_VIDEO"      : False,
            "UPLOAD_KEOGRAM"         : False,
            "UPLOAD_STARTRAIL"       : False,
            "UPLOAD_STARTRAIL_VIDEO" : False,
            "UPLOAD_PANORAMA_VIDEO"  : False,
            "UPLOAD_ENDOFNIGHT"      : False,
            "FORCE_IPV4"             : False,
            "FORCE_IPV6"             : False,
            "LIBCURL_OPTIONS"        : {},
        },
        "S3UPLOAD" : {
            "ENABLE"                 : False,
            "CLASSNAME"              : "boto3_s3",
            "ACCESS_KEY"             : "",
            "SECRET_KEY"             : "",
            "SECRET_KEY_E"           : "",
            "CREDS_FILE"             : "",
            "BUCKET"                 : "change-me",
            "REGION"                 : "us-east-2",
            "NAMESPACE"              : "",
            "HOST"                   : "amazonaws.com",
            "PORT"                   : 0,
            "CONNECT_TIMEOUT"        : 10.0,
            "TIMEOUT"                : 60.0,
            "URL_TEMPLATE"           : "https://{bucket}.s3.{region}.{host}",
            "ACL"                    : "",
            "STORAGE_CLASS"          : "STANDARD",
            "TLS"                    : True,
            "CERT_BYPASS"            : False,
            "UPLOAD_FITS"            : False,
            "UPLOAD_RAW"             : False,
        },
        "MQTTPUBLISH" : {
            "ENABLE"                 : False,
            "TRANSPORT"              : "tcp",  # tcp or websockets
            "HOST"                   : "localhost",
            "PORT"                   : 8883,  # 1883 = mqtt, 8883 = TLS
            "USERNAME"               : "indi-allsky",
            "PASSWORD"               : "",
            "PASSWORD_E"             : "",
            "BASE_TOPIC"             : "indi-allsky",
            "QOS"                    : 0,  # 0, 1, or 2
            "TLS"                    : True,
            "CERT_BYPASS"            : True,
            "PUBLISH_IMAGE"          : True,
        },
        "SYNCAPI" : {
            "ENABLE"                 : False,
            "BASEURL"                : "https://example.com/indi-allsky",
            "USERNAME"               : "",
            "APIKEY"                 : "",
            "APIKEY_E"               : "",
            "CERT_BYPASS"            : False,
            "POST_S3"                : False,
            "EMPTY_FILE"             : False,
            "UPLOAD_IMAGE"           : 1,
            "UPLOAD_PANORAMA"        : 1,
            #"UPLOAD_VIDEO"           : True,  # this cannot be changed
            "CONNECT_TIMEOUT"        : 10.0,
            "TIMEOUT"                : 60.0,
        },
        "YOUTUBE" : {
            "ENABLE"                 : False,
            "SECRETS_FILE"           : "",
            "PRIVACY_STATUS"         : "private",
            "TITLE_TEMPLATE"         : "Allsky {asset_label} - {day_date:%Y-%m-%d} - {timeofday}",
            "DESCRIPTION_TEMPLATE"   : "",
            "CATEGORY"               : 22,
            "TAGS"                   : ["allsky", "timelapse", "astronomy"],
            "UPLOAD_VIDEO"           : False,
            "UPLOAD_MINI_VIDEO"      : False,
            "UPLOAD_STARTRAIL_VIDEO" : False,
            "UPLOAD_PANORAMA_VIDEO"  : False,
        },
        "LIBCAMERA" : {
            "IMAGE_FILE_TYPE"        : "jpg",
            "IMAGE_FILE_TYPE_DAY"    : "jpg",
            "AWB"                    : "auto",
            "AWB_DAY"                : "auto",
            "AWB_ENABLE"             : False,
            "AWB_ENABLE_DAY"         : False,
            "CAMERA_ID"              : 0,
            "EXTRA_OPTIONS"          : "",
            "EXTRA_OPTIONS_DAY"      : "",
        },
        "PYCURL_CAMERA" : {
            "URL"                    : '',
            "IMAGE_FILE_TYPE"        : "jpg",  # jpg, png
            "USERNAME"               : "",
            "PASSWORD"               : "",
            "PASSWORD_E"             : "",
        },
        "ACCUM_CAMERA" : {
            "SUB_EXPOSURE_MAX"       : 1.0,
            "EVEN_EXPOSURES"         : True,
        },
        "FOCUSER" : {
            "CLASSNAME"              : "",
            "GPIO_PIN_1"             : "D17",
            "GPIO_PIN_2"             : "D18",
            "GPIO_PIN_3"             : "D27",
            "GPIO_PIN_4"             : "D22",
        },
        "DEW_HEATER" : {
            "CLASSNAME"              : "",
            "ENABLE_DAY"             : False,
            "PIN_1"                  : "D12",
            "INVERT_OUTPUT"          : False,
            "LEVEL_DEF"              : 100,
            "THOLD_ENABLE "          : False,
            "MANUAL_TARGET"          : 0.0,
            "TEMP_USER_VAR_SLOT"     : "sensor_user_10",
            "DEWPOINT_USER_VAR_SLOT" : "sensor_user_2",
            "LEVEL_LOW"              : 33,
            "LEVEL_MED"              : 66,
            "LEVEL_HIGH"             : 100,
            "THOLD_DIFF_LOW"         : 15,
            "THOLD_DIFF_MED"         : 10,
            "THOLD_DIFF_HIGH"        : 5,
        },
        "FAN" : {
            "CLASSNAME"              : "",
            "ENABLE_NIGHT"           : False,
            "PIN_1"                  : "D13",
            "INVERT_OUTPUT"          : False,
            "LEVEL_DEF"              : 100,
            "THOLD_ENABLE "          : False,
            "TARGET"                 : 30.0,
            "TEMP_USER_VAR_SLOT"     : "sensor_user_10",
            "LEVEL_LOW"              : 33,
            "LEVEL_MED"              : 66,
            "LEVEL_HIGH"             : 100,
            "THOLD_DIFF_LOW"         : -10,
            "THOLD_DIFF_MED"         : -5,
            "THOLD_DIFF_HIGH"        : 0,
        },
        "GENERIC_GPIO" : {
            "A_CLASSNAME"            : "",
            "A_PIN_1"                : "D21",
            "A_INVERT_OUTPUT"        : False,
        },
        "TEMP_SENSOR" : {
            "A_CLASSNAME"            : "",
            "A_LABEL"                : "Sensor A",
            "A_PIN_1"                : "D5",
            "A_USER_VAR_SLOT"        : "sensor_user_10",
            "A_I2C_ADDRESS"          : "0x77",
            "B_CLASSNAME"            : "",
            "B_LABEL"                : "Sensor B",
            "B_PIN_1"                : "D6",
            "B_USER_VAR_SLOT"        : "sensor_user_15",
            "B_I2C_ADDRESS"          : "0x76",
            "C_CLASSNAME"            : "",
            "C_LABEL"                : "Sensor C",
            "C_PIN_1"                : "D16",
            "C_USER_VAR_SLOT"        : "sensor_user_20",
            "C_I2C_ADDRESS"          : "0x40",
            "OPENWEATHERMAP_APIKEY"  : "",
            "OPENWEATHERMAP_APIKEY_E": "",
            "WUNDERGROUND_APIKEY"    : "",
            "WUNDERGROUND_APIKEY_E"  : "",
            "ASTROSPHERIC_APIKEY"    : "",
            "ASTROSPHERIC_APIKEY_E"  : "",
            "AMBIENTWEATHER_APIKEY"           : "",
            "AMBIENTWEATHER_APIKEY_E"         : "",
            "AMBIENTWEATHER_APPLICATIONKEY"   : "",
            "AMBIENTWEATHER_APPLICATIONKEY_E" : "",
            "AMBIENTWEATHER_MACADDRESS"       : "",
            "AMBIENTWEATHER_MACADDRESS_E"     : "",
            "ECOWITT_APIKEY"           : "",
            "ECOWITT_APIKEY_E"         : "",
            "ECOWITT_MACADDRESS_E"     : "",
            "ECOWITT_APPLICATIONKEY"   : "",
            "ECOWITT_APPLICATIONKEY_E" : "",
            "ECOWITT_MACADDRESS"       : "",
            "MQTT_TRANSPORT"         : "tcp",  # tcp or websockets
            "MQTT_HOST"              : "localhost",
            "MQTT_PORT"              : 8883,  # 1883 = mqtt, 8883 = TLS
            "MQTT_USERNAME"          : "indi-allsky",
            "MQTT_PASSWORD"          : "",
            "MQTT_PASSWORD_E"        : "",
            "MQTT_TLS"               : True,
            "MQTT_CERT_BYPASS"       : True,
            "SHT3X_HEATER_NIGHT"     : False,
            "SHT3X_HEATER_DAY"       : False,
            "HTU31D_HEATER_NIGHT"    : False,
            "HTU31D_HEATER_DAY"      : False,
            "SHT4X_MODE_NIGHT"       : "NOHEAT_HIGHPRECISION",
            "SHT4X_MODE_DAY"         : "NOHEAT_HIGHPRECISION",
            "HDC302X_HEATER_NIGHT"   : "OFF",
            "HDC302X_HEATER_DAY"     : "OFF",
            "SI7021_HEATER_LEVEL_NIGHT" : -1,
            "SI7021_HEATER_LEVEL_DAY"   : -1,
            "TSL2561_GAIN_NIGHT"     : 1,  # 0=1x, 1=16x
            "TSL2561_GAIN_DAY"       : 0,
            "TSL2561_INT_NIGHT"      : 1,  # 0=13.7ms, 1=101ms, 2=402ms, or 3=manual
            "TSL2561_INT_DAY"        : 1,
            "TSL2591_GAIN_NIGHT"     : "GAIN_MED",
            "TSL2591_GAIN_DAY"       : "GAIN_LOW",
            "TSL2591_INT_NIGHT"      : "INTEGRATIONTIME_100MS",
            "TSL2591_INT_DAY"        : "INTEGRATIONTIME_100MS",
            "VEML7700_GAIN_NIGHT"    : "ALS_GAIN_1",
            "VEML7700_GAIN_DAY"      : "ALS_GAIN_1_8",
            "VEML7700_INT_NIGHT"     : "ALS_100MS",
            "VEML7700_INT_DAY"       : "ALS_100MS",
            "SI1145_VIS_GAIN_NIGHT"  : "GAIN_ADC_CLOCK_DIV_32",
            "SI1145_VIS_GAIN_DAY"    : "GAIN_ADC_CLOCK_DIV_1",
            "SI1145_IR_GAIN_NIGHT"   : "GAIN_ADC_CLOCK_DIV_32",
            "SI1145_IR_GAIN_DAY"     : "GAIN_ADC_CLOCK_DIV_1",
            "LTR390_GAIN_NIGHT"      : "GAIN_9X",
            "LTR390_GAIN_DAY"        : "GAIN_1X",
        },
        "CHARTS" : {
            "CUSTOM_SLOT_1"          : "sensor_user_10",
            "CUSTOM_SLOT_2"          : "sensor_user_11",
            "CUSTOM_SLOT_3"          : "sensor_user_12",
            "CUSTOM_SLOT_4"          : "sensor_user_13",
            "CUSTOM_SLOT_5"          : "sensor_user_14",
            "CUSTOM_SLOT_6"          : "sensor_user_15",
            "CUSTOM_SLOT_7"          : "sensor_user_16",
            "CUSTOM_SLOT_8"          : "sensor_user_17",
            "CUSTOM_SLOT_9"          : "sensor_user_18",
        },
        "ADSB" : {
            "ENABLE"                 : False,
            "DUMP1090_URL"           : 'https://localhost/dump1090/data/aircraft.json',
            "CERT_BYPASS"            : True,
            "USERNAME"               : "",
            "PASSWORD"               : "",
            "PASSWORD_E"             : "",
            "ALT_DEG_MIN"            : 20.0,
            "LABEL_ENABLE"           : True,
            "LABEL_LIMIT"            : 10,
            "AIRCRAFT_LABEL_TEMPLATE"      : "{id:s} {distance:0.1f}km {alt:0.1f}\u00b0 {dir:s}",
            "IMAGE_LABEL_TEMPLATE_PREFIX"  : "# xy:15,300 (Left)\n# anchor:la (Left Justified)\n# color:200,200,200\nAircraft",
        },
        "SATELLITE_TRACK" : {
            "ENABLE"                 : False,
            "DAYTIME_TRACK"          : False,
            "ALT_DEG_MIN"            : 20.0,
            "LABEL_ENABLE"           : True,
            "LABEL_LIMIT"            : 10,
            "SAT_LABEL_TEMPLATE"     : "{title:s} {alt:0.1f}\u00b0 {dir:s}",
            "IMAGE_LABEL_TEMPLATE_PREFIX" : "# xy:-15,200 (Right)\n# anchor:ra (Right Justified)\n# color:200,200,200\nSatellites",
        },
    })


    @property
    def base_config(self):
        return self._base_config

    @base_config.setter
    def base_config(self, new_base_config):
        pass  # read only


class IndiAllSkyConfig(IndiAllSkyConfigBase):

    def __init__(self):
        self._config = self.base_config.copy()  # populate initial values

        # fetch latest config
        config_entry = self._getConfigEntry()

        # apply config on top of template
        self._config_id = config_entry.id
        self._config_level = config_entry.level
        self._createDate = config_entry.createDate
        self._config.update(config_entry.data)

        self._config = self._decrypt_passwords()


    @property
    def config(self):
        return self._config

    @property
    def config_id(self):
        return self._config_id

    @property
    def config_level(self):
        return self._config_level

    @property
    def createDate(self):
        return self._createDate


    def _getConfigEntry(self, config_id=None):
        ### return the last saved config entry
        utcnow = datetime.now(tz=timezone.utc).replace(tzinfo=None)  # configs stored with UTC

        future_configs = IndiAllSkyDbConfigTable.query\
            .filter(IndiAllSkyDbConfigTable.createDate > utcnow)\
            .first()

        if future_configs:
            logger.warning('!!! CONFIGURATIONS FOUND WITH A TIMESTAMP IN THE FUTURE, TIME MAY HAVE CHANGED !!!')


        if config_id:
            # not catching NoResultFound
            config_entry = IndiAllSkyDbConfigTable.query\
                .filter(IndiAllSkyDbConfigTable.id == int(config_id))\
                .one()
        else:
            # not catching NoResultFound
            config_entry = IndiAllSkyDbConfigTable.query\
                .order_by(IndiAllSkyDbConfigTable.createDate.desc())\
                .limit(1)\
                .one()


        return config_entry


    def _setConfigEntry(self, config, user_entry, note, encrypted):
        ### Always store configs with UTC
        utcnow = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        config_entry = IndiAllSkyDbConfigTable(
            data=config,
            createDate=utcnow,
            level=str(__config_level__),
            user_id=user_entry.id,
            note=str(note),
            encrypted=encrypted,
        )

        db.session.add(config_entry)
        db.session.commit()

        return config_entry


    def _decrypt_passwords(self):
        config = self._config.copy()

        if config['ENCRYPT_PASSWORDS']:
            f_key = Fernet(app.config['PASSWORD_KEY'].encode())

            filetransfer__password_e = config.get('FILETRANSFER', {}).get('PASSWORD_E', '')
            if filetransfer__password_e:
                # not catching InvalidToken
                filetransfer__password = f_key.decrypt(filetransfer__password_e.encode()).decode()
            else:
                filetransfer__password = config.get('FILETRANSFER', {}).get('PASSWORD', '')


            s3upload__secret_key_e = config.get('S3UPLOAD', {}).get('SECRET_KEY_E', '')
            if s3upload__secret_key_e:
                # not catching InvalidToken
                s3upload__secret_key = f_key.decrypt(s3upload__secret_key_e.encode()).decode()
            else:
                s3upload__secret_key = config.get('S3UPLOAD', {}).get('SECRET_KEY', '')


            mqttpublish__password_e = config.get('MQTTPUBLISH', {}).get('PASSWORD_E', '')
            if mqttpublish__password_e:
                # not catching InvalidToken
                mqttpublish__password = f_key.decrypt(mqttpublish__password_e.encode()).decode()
            else:
                mqttpublish__password = config.get('MQTTPUBLISH', {}).get('PASSWORD', '')


            syncapi__apikey_e = config.get('SYNCAPI', {}).get('APIKEY_E', '')
            if syncapi__apikey_e:
                # not catching InvalidToken
                syncapi__apikey = f_key.decrypt(syncapi__apikey_e.encode()).decode()
            else:
                syncapi__apikey = config.get('SYNCAPI', {}).get('APIKEY', '')


            pycurl_camera__password_e = config.get('PYCURL_CAMERA', {}).get('PASSWORD_E', '')
            if pycurl_camera__password_e:
                # not catching InvalidToken
                pycurl_camera__password = f_key.decrypt(pycurl_camera__password_e.encode()).decode()
            else:
                pycurl_camera__password = config.get('PYCURL_CAMERA', {}).get('PASSWORD', '')


            temp_sensor__openweathermap_apikey_e = config.get('TEMP_SENSOR', {}).get('OPENWEATHERMAP_APIKEY_E', '')
            if temp_sensor__openweathermap_apikey_e:
                # not catching InvalidToken
                temp_sensor__openweathermap_apikey = f_key.decrypt(temp_sensor__openweathermap_apikey_e.encode()).decode()
            else:
                temp_sensor__openweathermap_apikey = config.get('TEMP_SENSOR', {}).get('OPENWEATHERMAP_APIKEY', '')


            temp_sensor__wunderground_apikey_e = config.get('TEMP_SENSOR', {}).get('WUNDERGROUND_APIKEY_E', '')
            if temp_sensor__wunderground_apikey_e:
                # not catching InvalidToken
                temp_sensor__wunderground_apikey = f_key.decrypt(temp_sensor__wunderground_apikey_e.encode()).decode()
            else:
                temp_sensor__wunderground_apikey = config.get('TEMP_SENSOR', {}).get('WUNDERGROUND_APIKEY', '')


            temp_sensor__astrospheric_apikey_e = config.get('TEMP_SENSOR', {}).get('ASTROSPHERIC_APIKEY_E', '')
            if temp_sensor__astrospheric_apikey_e:
                # not catching InvalidToken
                temp_sensor__astrospheric_apikey = f_key.decrypt(temp_sensor__astrospheric_apikey_e.encode()).decode()
            else:
                temp_sensor__astrospheric_apikey = config.get('TEMP_SENSOR', {}).get('ASTROSPHERIC_APIKEY', '')


            temp_sensor__mqtt_password_e = config.get('TEMP_SENSOR', {}).get('MQTT_PASSWORD_E', '')
            if temp_sensor__mqtt_password_e:
                # not catching InvalidToken
                temp_sensor__mqtt_password = f_key.decrypt(temp_sensor__mqtt_password_e.encode()).decode()
            else:
                temp_sensor__mqtt_password = config.get('TEMP_SENSOR', {}).get('MQTT_PASSWORD', '')


            adsb__password_e = config.get('ADSB', {}).get('PASSWORD_E', '')
            if adsb__password_e:
                # not catching InvalidToken
                adsb__password = f_key.decrypt(adsb__password_e.encode()).decode()
            else:
                adsb__password = config.get('ADSB', {}).get('PASSWORD', '')

        else:
            # passwords should not be encrypted
            filetransfer__password = config.get('FILETRANSFER', {}).get('PASSWORD', '')
            s3upload__secret_key = config.get('S3UPLOAD', {}).get('SECRET_KEY', '')
            mqttpublish__password = config.get('MQTTPUBLISH', {}).get('PASSWORD', '')
            syncapi__apikey = config.get('SYNCAPI', {}).get('APIKEY', '')
            pycurl_camera__password = config.get('PYCURL_CAMERA', {}).get('PASSWORD', '')
            temp_sensor__openweathermap_apikey = config.get('TEMP_SENSOR', {}).get('OPENWEATHERMAP_APIKEY', '')
            temp_sensor__wunderground_apikey = config.get('TEMP_SENSOR', {}).get('WUNDERGROUND_APIKEY', '')
            temp_sensor__astrospheric_apikey = config.get('TEMP_SENSOR', {}).get('ASTROSPHERIC_APIKEY', '')
            temp_sensor__mqtt_password = config.get('TEMP_SENSOR', {}).get('MQTT_PASSWORD', '')
            adsb__password = config.get('ADSB', {}).get('PASSWORD', '')


        config['FILETRANSFER']['PASSWORD'] = filetransfer__password
        config['FILETRANSFER']['PASSWORD_E'] = ''
        config['S3UPLOAD']['SECRET_KEY'] = s3upload__secret_key
        config['S3UPLOAD']['SECRET_KEY_E'] = ''
        config['MQTTPUBLISH']['PASSWORD'] = mqttpublish__password
        config['MQTTPUBLISH']['PASSWORD_E'] = ''
        config['SYNCAPI']['APIKEY'] = syncapi__apikey
        config['SYNCAPI']['APIKEY_E'] = ''
        config['PYCURL_CAMERA']['PASSWORD'] = pycurl_camera__password
        config['PYCURL_CAMERA']['PASSWORD_E'] = ''
        config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY'] = temp_sensor__openweathermap_apikey
        config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY_E'] = ''
        config['TEMP_SENSOR']['WUNDERGROUND_APIKEY'] = temp_sensor__wunderground_apikey
        config['TEMP_SENSOR']['WUNDERGROUND_APIKEY_E'] = ''
        config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY'] = temp_sensor__astrospheric_apikey
        config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY_E'] = ''
        config['TEMP_SENSOR']['MQTT_PASSWORD'] = temp_sensor__mqtt_password
        config['TEMP_SENSOR']['MQTT_PASSWORD_E'] = ''
        config['ADSB']['PASSWORD'] = adsb__password
        config['ADSB']['PASSWORD_E'] = ''

        return config


    def save(self, username, note):
        user_entry = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == str(username))\
            .one()


        config, encrypted = self._encryptPasswords()

        config_entry = self._setConfigEntry(config, user_entry, note, encrypted)

        self._config_id = config_entry.id

        return config_entry


    def _encryptPasswords(self):
        config = self._config.copy()

        if config['ENCRYPT_PASSWORDS']:
            encrypted = True

            f_key = Fernet(app.config['PASSWORD_KEY'].encode())

            filetransfer__password = str(config['FILETRANSFER']['PASSWORD'])
            if filetransfer__password:
                filetransfer__password_e = f_key.encrypt(filetransfer__password.encode()).decode()
                filetransfer__password = ''
            else:
                filetransfer__password_e = ''
                filetransfer__password = ''


            s3upload__secret_key = str(config['S3UPLOAD']['SECRET_KEY'])
            if s3upload__secret_key:
                s3upload__secret_key_e = f_key.encrypt(s3upload__secret_key.encode()).decode()
                s3upload__secret_key = ''
            else:
                s3upload__secret_key_e = ''
                s3upload__secret_key = ''


            mqttpublish__password = str(config['MQTTPUBLISH']['PASSWORD'])
            if mqttpublish__password:
                mqttpublish__password_e = f_key.encrypt(mqttpublish__password.encode()).decode()
                mqttpublish__password = ''
            else:
                mqttpublish__password_e = ''
                mqttpublish__password = ''


            syncapi__apikey = str(config['SYNCAPI']['APIKEY'])
            if syncapi__apikey:
                syncapi__apikey_e = f_key.encrypt(syncapi__apikey.encode()).decode()
                syncapi__apikey = ''
            else:
                syncapi__apikey_e = ''
                syncapi__apikey = ''


            pycurl_camera__password = str(config['PYCURL_CAMERA']['PASSWORD'])
            if pycurl_camera__password:
                pycurl_camera__password_e = f_key.encrypt(pycurl_camera__password.encode()).decode()
                pycurl_camera__password = ''
            else:
                pycurl_camera__password_e = ''
                pycurl_camera__password = ''


            temp_sensor__openweathermap_apikey = str(config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY'])
            if temp_sensor__openweathermap_apikey:
                temp_sensor__openweathermap_apikey_e = f_key.encrypt(temp_sensor__openweathermap_apikey.encode()).decode()
                temp_sensor__openweathermap_apikey = ''
            else:
                temp_sensor__openweathermap_apikey_e = ''
                temp_sensor__openweathermap_apikey = ''


            temp_sensor__wunderground_apikey = str(config['TEMP_SENSOR']['WUNDERGROUND_APIKEY'])
            if temp_sensor__wunderground_apikey:
                temp_sensor__wunderground_apikey_e = f_key.encrypt(temp_sensor__wunderground_apikey.encode()).decode()
                temp_sensor__wunderground_apikey = ''
            else:
                temp_sensor__wunderground_apikey_e = ''
                temp_sensor__wunderground_apikey = ''


            temp_sensor__astrospheric_apikey = str(config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY'])
            if temp_sensor__astrospheric_apikey:
                temp_sensor__astrospheric_apikey_e = f_key.encrypt(temp_sensor__astrospheric_apikey.encode()).decode()
                temp_sensor__astrospheric_apikey = ''
            else:
                temp_sensor__astrospheric_apikey_e = ''
                temp_sensor__astrospheric_apikey = ''


            temp_sensor__mqtt_password = str(config['TEMP_SENSOR']['MQTT_PASSWORD'])
            if temp_sensor__mqtt_password:
                temp_sensor__mqtt_password_e = f_key.encrypt(temp_sensor__mqtt_password.encode()).decode()
                temp_sensor__mqtt_password = ''
            else:
                temp_sensor__mqtt_password_e = ''
                temp_sensor__mqtt_password = ''


            adsb__password = str(config['ADSB']['PASSWORD'])
            if adsb__password:
                adsb__password_e = f_key.encrypt(adsb__password.encode()).decode()
                adsb__password = ''
            else:
                adsb__password_e = ''
                adsb__password = ''

        else:
            # passwords should not be encrypted
            encrypted = False

            filetransfer__password = str(config['FILETRANSFER']['PASSWORD'])
            filetransfer__password_e = ''
            s3upload__secret_key = str(config['S3UPLOAD']['SECRET_KEY'])
            s3upload__secret_key_e = ''
            mqttpublish__password = str(config['MQTTPUBLISH']['PASSWORD'])
            mqttpublish__password_e = ''
            syncapi__apikey = str(config['SYNCAPI']['APIKEY'])
            syncapi__apikey_e = ''
            pycurl_camera__password = str(config['PYCURL_CAMERA']['PASSWORD'])
            pycurl_camera__password_e = ''
            temp_sensor__openweathermap_apikey = str(config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY'])
            temp_sensor__openweathermap_apikey_e = ''
            temp_sensor__wunderground_apikey = str(config['TEMP_SENSOR']['WUNDERGROUND_APIKEY'])
            temp_sensor__wunderground_apikey_e = ''
            temp_sensor__astrospheric_apikey = str(config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY'])
            temp_sensor__astrospheric_apikey_e = ''
            temp_sensor__mqtt_password = str(config['TEMP_SENSOR']['MQTT_PASSWORD'])
            temp_sensor__mqtt_password_e = ''
            adsb__password = str(config['ADSB']['PASSWORD'])
            adsb__password_e = ''


        config['FILETRANSFER']['PASSWORD'] = filetransfer__password
        config['FILETRANSFER']['PASSWORD_E'] = filetransfer__password_e
        config['S3UPLOAD']['SECRET_KEY'] = s3upload__secret_key
        config['S3UPLOAD']['SECRET_KEY_E'] = s3upload__secret_key_e
        config['MQTTPUBLISH']['PASSWORD'] = mqttpublish__password
        config['MQTTPUBLISH']['PASSWORD_E'] = mqttpublish__password_e
        config['SYNCAPI']['APIKEY'] = syncapi__apikey
        config['SYNCAPI']['APIKEY_E'] = syncapi__apikey_e
        config['PYCURL_CAMERA']['PASSWORD'] = pycurl_camera__password
        config['PYCURL_CAMERA']['PASSWORD_E'] = pycurl_camera__password_e
        config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY'] = temp_sensor__openweathermap_apikey
        config['TEMP_SENSOR']['OPENWEATHERMAP_APIKEY_E'] = temp_sensor__openweathermap_apikey_e
        config['TEMP_SENSOR']['WUNDERGROUND_APIKEY'] = temp_sensor__wunderground_apikey
        config['TEMP_SENSOR']['WUNDERGROUND_APIKEY_E'] = temp_sensor__wunderground_apikey_e
        config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY'] = temp_sensor__astrospheric_apikey
        config['TEMP_SENSOR']['ASTROSPHERIC_APIKEY_E'] = temp_sensor__astrospheric_apikey_e
        config['TEMP_SENSOR']['MQTT_PASSWORD'] = temp_sensor__mqtt_password
        config['TEMP_SENSOR']['MQTT_PASSWORD_E'] = temp_sensor__mqtt_password_e
        config['ADSB']['PASSWORD'] = adsb__password
        config['ADSB']['PASSWORD_E'] = adsb__password_e


        return config, encrypted


class IndiAllSkyConfigUtil(IndiAllSkyConfig):

    def __init__(self):
        # not calling parent constructor
        self._config = self.base_config.copy()  # populate initial values


    def bootstrap(self, **kwargs):
        with app.app_context():
            self._bootstrap(**kwargs)


    def _bootstrap(self, **kwargs):
        try:
            self._getConfigEntry()

            logger.warning('Configuration already initialized')

            sys.exit(1)
        except NoResultFound:
            pass


        self._createSystemAccount()


        logger.info('Creating initial configuration')
        self.save('system', 'Initial config')


    def list(self, **kwargs):
        with app.app_context():
            self._list(**kwargs)


    def _list(self, **kwargs):
        table = PrettyTable()
        table.field_names = ['ID', 'Create Date', 'User ID', 'Level', 'Note']

        config_list = IndiAllSkyDbConfigTable.query\
            .order_by(IndiAllSkyDbConfigTable.createDate.desc())

        for config in config_list:
            table.add_row([config.id, config.createDate, config.user_id, config.level, config.note])

        print(table)


    def load(self, **kwargs):
        with app.app_context():
            self._load(**kwargs)


    def _load(self, **kwargs):
        f_config = kwargs['config']
        force = kwargs['force']

        if not force:
            try:
                self._getConfigEntry()

                logger.error('Configuration already defined, not loading config')

                sys.exit(1)
            except NoResultFound:
                pass


        self._createSystemAccount()


        c = json.loads(f_config.read(), object_pairs_hook=OrderedDict)
        f_config.close()


        # check a few values to make sure this is a valid config
        if not c.get('INDI_SERVER') or not c.get('NIGHT_SUN_ALT_DEG') or not c.get('CCD_CONFIG'):
            logger.error('Not a valid indi-allsky config')
            sys.exit(1)


        self.config.update(c)

        logger.info('Loading configuration from file')
        self.save('system', 'Load config: {0:s}'.format(f_config.name))


    def update_level(self, **kwargs):
        with app.app_context():
            self._update_level(**kwargs)


    def _update_level(self, **kwargs):
        # fetch latest config
        try:
            config_entry = self._getConfigEntry()
        except NoResultFound:
            logger.error('Configuration not loaded')
            sys.exit(1)


        self._config.update(config_entry.data)

        logger.info('Updating config level')
        self.save('system', 'Update config level: {0:s}'.format(__config_level__))


    def edit(self, **kwargs):
        with app.app_context():
            self._edit(**kwargs)


    def _edit(self, **kwargs):
        try:
            config_entry = self._getConfigEntry()
        except NoResultFound:
            logger.error('Configuration not loaded')
            sys.exit(1)


        self._config.update(config_entry.data)

        self._config = self._decrypt_passwords()

        config_temp_f = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(
            self.config,
            config_temp_f,
            indent=4,
            ensure_ascii=False,
        )
        config_temp_f.close()

        config_temp_p = Path(config_temp_f.name)

        initial_mtime = config_temp_p.stat().st_mtime


        while True:
            # execute until JSON is correctly formatted
            os.system('editor {0:s}'.format(str(config_temp_p)))

            try:
                with io.open(str(config_temp_p), 'r') as f_config:
                    new_config = json.loads(f_config.read(), object_pairs_hook=OrderedDict)

                break
            except json.JSONDecodeError:
                logger.error('JSON formatting error')
                time.sleep(3.0)


        if config_temp_p.stat().st_mtime == initial_mtime:
            logger.info('Config not updated')
            config_temp_p.unlink()  # cleanup
            return


        self.config.update(new_config)

        logger.info('Saving new config')
        self.save('system', 'CLI config edit')

        config_temp_p.unlink()  # cleanup


    def revert(self, **kwargs):
        with app.app_context():
            self._revert(**kwargs)


    def _revert(self, **kwargs):
        revert_id = kwargs['config_id']

        try:
            revert_entry = self._getConfigEntry(config_id=revert_id)
        except NoResultFound:
            logger.error('Configuration ID %d not found', int(revert_id))
            sys.exit(1)


        self._config.update(revert_entry.data)

        logger.info('Reverting configuration')
        self.save('system', 'Revert to config: {0:d}'.format(revert_entry.id))


    def dump(self, **kwargs):
        with app.app_context():
            self._dump(**kwargs)


    def _dump(self, **kwargs):
        dump_id = kwargs['config_id']

        try:
            dump_entry = self._getConfigEntry(config_id=dump_id)
        except NoResultFound:
            logger.error('Configuration ID %d not found', int(dump_id))
            sys.exit(1)

        self._config.update(dump_entry.data)

        self._config = self._decrypt_passwords()

        logger.info('Dumping config')

        print(json.dumps(self._config, indent=4, ensure_ascii=False))


    def user_count(self, **kwargs):
        with app.app_context():
            self._user_count(**kwargs)


    def _user_count(self, **kwargs):
        user_count = IndiAllSkyDbUserTable.query.count()
        print('{0:d}'.format(user_count))


    def flush(self, **kwargs):
        with app.app_context():
            self._flush(**kwargs)


    def _flush(self, **kwargs):
        confirm1 = input('\nConfirm flushing all configs? [y/n] ')
        if confirm1.lower() != 'y':
            logger.warning('Cancel flush')
            sys.exit(1)

        confirm2 = input('\nAre you lying? [y/n] ')
        if confirm2.lower() != 'n':
            logger.warning('Cancel flush')
            sys.exit(1)

        rand_int = random.randint(1000, 9999)
        confirm3 = input('\nEnter the number {0:d} backwards to confirm: '.format(rand_int))
        if confirm3 != str(rand_int)[::-1]:
            logger.warning('Cancel flush')
            sys.exit(1)

        configs_all = IndiAllSkyDbConfigTable.query
        configs_all.delete()
        db.session.commit()

        logger.info('All configurations have been deleted')


    def _createSystemAccount(self):
        try:
            system_user = IndiAllSkyDbUserTable.query\
                .filter(IndiAllSkyDbUserTable.username == 'system')\
                .one()

            return system_user
        except NoResultFound:
            pass


        system_user = IndiAllSkyDbUserTable(
            username='system',
            password='disabled',
            name='Internal System Account',
            email='system@indi-allsky',
            active=False,
            admin=True,
        )

        db.session.add(system_user)
        db.session.commit()

        return system_user

