import sys
import os
import time
import io
import json
import tempfile
from pathlib import Path
from collections import OrderedDict
import logging

from .flask.models import IndiAllSkyDbConfigTable
from .flask.models import IndiAllSkyDbUserTable

from .flask import db

from sqlalchemy.orm.exc import NoResultFound

from .version import __config_level__


logger = logging.getLogger('indi_allsky')


class IndiAllSkyConfigBase(object):

    _base_config = OrderedDict({
        "CAMERA_INTERFACE" : "indi",
        "INDI_SERVER" : "localhost",
        "INDI_PORT"   : 7624,
        "INDI_CAMERA_NAME" : "",
        "CCD_CONFIG" : {
            "NIGHT" : {
                "GAIN"    : 100,
                "BINNING" : 1
            },
            "MOONMODE" : {
                "GAIN"    : 75,
                "BINNING" : 1
            },
            "DAY" : {
                "GAIN"    : 0,
                "BINNING" : 1
            }
        },
        "INDI_CONFIG_DEFAULTS" : {
            "SWITCHES" : {},
            "PROPERTIES" : {},
            "TEXT" : {}
        },
        "CCD_EXPOSURE_MAX"     : 15.00000,
        "CCD_EXPOSURE_DEF"     : 0.0,
        "CCD_EXPOSURE_MIN"     : 0.0,
        "EXPOSURE_PERIOD"      : 15.00000,
        "EXPOSURE_PERIOD_DAY"  : 15.00000,
        "FOCUS_MODE"           : False,
        "FOCUS_DELAY"          : 4.0,
        "CFA_PATTERN"      : "",  # None, GRBG, RGGB, BGGR, GBRG
        "SCNR_ALGORITHM"   : "",  # empty string, average_neutral, or maximum_neutral
        "WBR_FACTOR"       : 1.0,
        "WBG_FACTOR"       : 1.0,
        "WBB_FACTOR"       : 1.0,
        "AUTO_WB"          : False,
        "CCD_COOLING"      : False,
        "CCD_TEMP"         : 15.0,
        "TEMP_DISPLAY"     : "c",  # c = celcius, f = fahrenheit, k = kelvin",
        "CCD_TEMP_SCRIPT"  : "",
        "GPS_TIMESYNC"     : False,
        "TARGET_ADU" : 75,
        "TARGET_ADU_DEV"     : 10,
        "TARGET_ADU_DEV_DAY" : 20,
        "ADU_ROI" : [],
        "DETECT_STARS" : True,
        "DETECT_STARS_THOLD" : 0.6,
        "DETECT_METEORS" : False,
        "DETECT_MASK" : "",
        "DETECT_DRAW" : False,
        "SQM_ROI" : [],
        "LOCATION_LATITUDE"  : 33,
        "LOCATION_LONGITUDE" : -84,
        "TIMELAPSE_ENABLE"         : True,
        "DAYTIME_CAPTURE"          : True,
        "DAYTIME_TIMELAPSE"        : True,
        "DAYTIME_CONTRAST_ENHANCE" : False,
        "NIGHT_CONTRAST_ENHANCE"   : False,
        "NIGHT_SUN_ALT_DEG"        : -6,
        "NIGHT_MOONMODE_ALT_DEG"   : 0,
        "NIGHT_MOONMODE_PHASE"     : 33,
        "WEB_EXTRA_TEXT" : "",
        "KEOGRAM_ANGLE"    : 0,
        "KEOGRAM_H_SCALE"  : 100,
        "KEOGRAM_V_SCALE"  : 33,
        "KEOGRAM_LABEL"    : True,
        "STARTRAILS_MAX_ADU"    : 50,
        "STARTRAILS_MASK_THOLD" : 190,
        "STARTRAILS_PIXEL_THOLD": 1.0,
        "STARTRAILS_TIMELAPSE"  : True,
        "STARTRAILS_TIMELAPSE_MINFRAMES" : 250,
        "IMAGE_FILE_TYPE" : "jpg",  # jpg, png, or tif
        "IMAGE_FILE_COMPRESSION" : {
            "jpg"   : 90,
            "png"   : 5,
            "tif"   : 5  # 5 = LZW
        },
        "IMAGE_FOLDER"     : "/var/www/html/allsky/images",
        "IMAGE_LABEL"      : True,
        "IMAGE_LABEL_TEMPLATE" : "{timestamp:%Y.%m.%d %H:%M:%S}\nLat {latitude:0.1f} Long {longitude:0.1f}\nExposure {exposure:0.6f}\nGain {gain:d}\nTemp {temp:0.1f}{temp_unit:s}\nStacking {stack_method:s}\nStars {stars:d}",
        "IMAGE_EXTRA_TEXT" : "",
        "IMAGE_CROP_ROI"   : [],
        "IMAGE_ROTATE"     : "",  # empty, ROTATE_90_CLOCKWISE, ROTATE_90_COUNTERCLOCKWISE, ROTATE_180
        "IMAGE_FLIP_V"     : True,
        "IMAGE_FLIP_H"     : True,
        "IMAGE_SCALE"      : 100,
        "NIGHT_GRAYSCALE"  : False,
        "DAYTIME_GRAYSCALE": False,
        "IMAGE_SAVE_FITS"     : False,
        "IMAGE_EXPORT_RAW"    : "",  # png or tif (or empty)
        "IMAGE_EXPORT_FOLDER" : "/var/www/html/allsky/images/export",
        "IMAGE_STACK_METHOD"  : "maximum",  # maximum, average, or minimum
        "IMAGE_STACK_COUNT"   : 1,
        "IMAGE_STACK_ALIGN"   : False,
        "IMAGE_ALIGN_DETECTSIGMA" : 5,
        "IMAGE_ALIGN_POINTS" : 50,
        "IMAGE_ALIGN_SOURCEMINAREA" : 10,
        "IMAGE_STACK_SPLIT"   : False,
        "IMAGE_EXPIRE_DAYS"     : 30,
        "TIMELAPSE_EXPIRE_DAYS" : 365,
        "FFMPEG_FRAMERATE" : 25,
        "FFMPEG_BITRATE"   : "2500k",
        "FFMPEG_VFSCALE"   : "",
        "FFMPEG_CODEC"     : "libx264",
        "FITSHEADERS" : [
            [ "INSTRUME", "indi-allsky" ],
            [ "OBSERVER", "" ],
            [ "SITE", "" ],
            [ "OBJECT", "" ],
            [ "NOTES", "" ]
        ],
        "TEXT_PROPERTIES" : {
            "DATE_FORMAT"    : "%Y%m%d %H:%M:%S",
            "FONT_FACE"      : "FONT_HERSHEY_SIMPLEX",
            "FONT_HEIGHT"    : 30,
            "FONT_X"         : 15,
            "FONT_Y"         : 30,
            "FONT_COLOR"     : [200, 200, 200],
            "FONT_AA"        : "LINE_AA",
            "FONT_SCALE"     : 0.80,
            "FONT_THICKNESS" : 1,
            "FONT_OUTLINE"   : True
        },
        "ORB_PROPERTIES" : {
            "MODE"        : "ha",  # ha = hour angle, az = azimuth, alt = altitude, off = off
            "RADIUS"      : 9,
            "SUN_COLOR"   : [255, 255, 255],
            "MOON_COLOR"  : [128, 128, 128]
        },
        "FILETRANSFER" : {
            "CLASSNAME"              : "pycurl_sftp",  # pycurl_sftp, pycurl_ftps, pycurl_ftpes, paramiko_sftp, python_ftp, python_ftpes
            "HOST"                   : "",
            "PORT"                   : 0,
            "USERNAME"               : "",
            "PASSWORD"               : "",
            "PRIVATE_KEY"            : "",
            "PUBLIC_KEY"             : "",
            "TIMEOUT"                : 5.0,
            "CERT_BYPASS"            : True,
            "REMOTE_IMAGE_NAME"      : "image.{0}",
            "REMOTE_IMAGE_FOLDER"        : "allsky",
            "REMOTE_METADATA_NAME"       : "latest_metadata.json",
            "REMOTE_METADATA_FOLDER"     : "allsky",
            "REMOTE_VIDEO_FOLDER"        : "allsky/videos",
            "REMOTE_KEOGRAM_FOLDER"      : "allsky/keograms",
            "REMOTE_STARTRAIL_FOLDER"    : "allsky/startrails",
            "REMOTE_ENDOFNIGHT_FOLDER"   : "allsky",
            "UPLOAD_IMAGE"           : 0,
            "UPLOAD_METADATA"        : False,
            "UPLOAD_VIDEO"           : False,
            "UPLOAD_KEOGRAM"         : False,
            "UPLOAD_STARTRAIL"       : False,
            "UPLOAD_ENDOFNIGHT"      : False,
            "LIBCURL_OPTIONS"        : {}
        },
        "MQTTPUBLISH" : {
            "ENABLE"                 : False,
            "TRANSPORT"              : "tcp",  # tcp or websockets
            "HOST"                   : "localhost",
            "PORT"                   : 8883,  # 1883 = mqtt, 8883 = TLS
            "USERNAME"               : "indi-allsky",
            "PASSWORD"               : "",
            "BASE_TOPIC"             : "indi-allsky",
            "QOS"                    : 0,  # 0, 1, or 2
            "TLS"                    : True,
            "CERT_BYPASS"            : True
        },
        "LIBCAMERA" : {
            "IMAGE_FILE_TYPE"        : "dng",
            "EXTRA_OPTIONS"          : ""
        }
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
        config_entry = self._getConfig()

        # apply config on top of template
        self._config_id = config_entry.id
        self._config_level = config_entry.level
        self._config.update(config_entry.data)



    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, new_config):
        pass  # read only


    @property
    def config_id(self):
        return self._config_id

    @config_id.setter
    def config_id(self, new_config_id):
        pass  # read only


    @property
    def config_level(self):
        return self._config_level

    @config_level.setter
    def config_level(self, new_config_level):
        pass  # read only


    def _getConfig(self):
        ### return the last saved config entry

        # not catching NoResultFound
        config_entry = IndiAllSkyDbConfigTable.query\
            .order_by(IndiAllSkyDbConfigTable.createDate.desc())\
            .limit(1)\
            .one()

        return config_entry


    def _setConfig(self, user_entry, note):
        config_entry = IndiAllSkyDbConfigTable(
            data=self._config,
            level=str(__config_level__),
            user_id=user_entry.id,
            note=str(note),
        )

        db.session.add(config_entry)
        db.session.commit()

        return config_entry


    def save(self, username, note):
        user_entry = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == str(username))\
            .one()

        config_entry = self._setConfig(user_entry, note)

        self._config_id = config_entry.id

        return config_entry


class IndiAllSkyConfigUtil(IndiAllSkyConfig):

    def __init__(self):
        self._config = self.base_config.copy()  # populate initial values


    def bootstrap(self, **kwargs):
        try:
            self._getConfig()

            logger.error('Configuration already initialized')

            sys.exit(1)
        except NoResultFound:
            pass


        self._createSystemAccount()


        logger.info('Creating initial configuration')
        self.save('system', 'Initial config')


    def load(self, **kwargs):
        f_config = kwargs['config']


        try:
            self._getConfig()

            logger.error('Configuration already defined, not loading config')

            sys.exit(1)
        except NoResultFound:
            pass


        self._createSystemAccount()


        c = json.loads(f_config.read(), object_pairs_hook=OrderedDict)
        f_config.close()

        self.config.update(c)

        logger.info('Loading configuration from file')
        self.save('system', 'Load config: {0:s}'.format(f_config.name))


    def update_level(self, **kwargs):
        # fetch latest config
        try:
            config_entry = self._getConfig()
            self._config.update(config_entry.data)
        except NoResultFound:
            logger.error('Configuration not loaded')
            sys.exit(1)


        logger.info('Updating config level')
        self.save('system', 'Update config level: {0:s}'.format(__config_level__))


    def edit(self, **kwargs):
        try:
            config_entry = self._getConfig()
            self._config.update(config_entry.data)
        except NoResultFound:
            logger.error('Configuration not loaded')
            sys.exit(1)


        config_temp_f = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        config_temp_f.write(json.dumps(self.config, indent=4))
        config_temp_f.close()

        config_temp_p = Path(config_temp_f.name)


        while True:
            # execute until JSON is correctly formatted
            os.system('editor {0:s}'.format(str(config_temp_p)))

            try:
                with io.open(str(config_temp_p), 'r') as f_config:
                    c = json.loads(f_config.read(), object_pairs_hook=OrderedDict)

                break
            except json.JSONDecodeError:
                logger.error('JSON formatting error')
                time.sleep(3.0)


        self.config.update(c)

        self.save('system', 'CLI config edit')

        config_temp_p.unlink()  # cleanup


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

