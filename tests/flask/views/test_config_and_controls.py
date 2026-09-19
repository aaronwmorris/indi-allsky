import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
)


@pytest.fixture
def config_db(flask_app):
    """Seed database for config and system control tests."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTaskQueueTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="33333333-3333-3333-3333-333333333333",
            latitude=-34.0,
            longitude=138.0,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
            hidden=False,
            utc_offset=36000.0,
            lensFocalLength=4.0,
            lensFocalRatio=2.0,
            lensImageCircle=180.0,
            cfa=None,
            owner="Admin",
            connectDate=db.func.now(),
            width=1920,
            height=1080,
            pixelSize=2.4,
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FOLDER': '/tmp',
                'INDI_PORT': 7624,
                'ALLSKYMAP': {'API_URL': 'https://allsky-map.com'},
            },
            level="1.0",
            note='test config',
        )
        db.session.add(config_entry)

        admin = IndiAllSkyDbUserTable(
            username="admin",
            password="hashed_password",
            email="admin@example.org",
            name="Admin",
            active=True,
            admin=True,
        )
        db.session.add(admin)

        system_user = IndiAllSkyDbUserTable(
            username="system",
            password="hashed_password",
            email="system@example.org",
            name="System",
            active=True,
            admin=True,
        )
        db.session.add(system_user)

        db.session.commit()
        yield
        db.session.remove()


def get_base_payload():
    return {
        'CAMERA_INTERFACE': 'indi',
        'INDI_SERVER': 'localhost',
        'INDI_PORT': 7624,
        'INDI_CAMERA_NAME': 'ASI CCD',
        'WEBSITE__TITLE': 'My Allsky',
        'OWNER': 'Observer',
        'LENS_NAME': 'AllSky Lens',
        'LENS_FOCAL_LENGTH': 2.5,
        'LENS_FOCAL_RATIO': 2.0,
        'LENS_IMAGE_CIRCLE': 3000,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'LENS_ALTITUDE': 90.0,
        'LENS_AZIMUTH': 0.0,
        'CCD_CONFIG__NIGHT__GAIN': 100.0,
        'CCD_CONFIG__NIGHT__BINNING': 1,
        'CCD_CONFIG__MOONMODE__GAIN': 75.0,
        'CCD_CONFIG__MOONMODE__BINNING': 1,
        'CCD_CONFIG__DAY__GAIN': 0.0,
        'CCD_CONFIG__DAY__BINNING': 1,
        'CCD_CONFIG__EXPOSURE_CLASSNAME': 'exposure_basic',
        'CCD_CONFIG__AUTO_GAIN_LEVELS': 8,
        'CCD_EXPOSURE_MAX': 15.0,
        'CCD_EXPOSURE_DEF': 1.0,
        'CCD_EXPOSURE_MIN': 0.001,
        'CCD_EXPOSURE_MIN_DAY': 0.0001,
        'CCD_EXPOSURE_TIMEOUT': 330,
        'CCD_BIT_DEPTH': 16,
        'EXPOSURE_PERIOD': 15.0,
        'EXPOSURE_PERIOD_DAY': 15.0,
        'CAMERA_SQM__ENABLE': False,
        'CAMERA_SQM__ENABLE_DAY': False,
        'CAMERA_SQM__EXPOSURE': 10.0,
        'CAMERA_SQM__GAIN': 10.0,
        'CAMERA_SQM__BINNING': 1,
        'CAMERA_SQM__EXPOSURE_PERIOD': 900,
        'CAMERA_SQM__MAGNITUDE_OFFSET': 25.0,
        'FOCUS_MODE': False,
        'FOCUS_DELAY': 4.0,
        'CFA_PATTERN': 'RGGB',
        'USE_NIGHT_COLOR': True,
        'SCNR_ALGORITHM': 'average_neutral',
        'SCNR_ALGORITHM_DAY': '',
        'SCNR_MTF_MIDTONES': 0.55,
        'SCNR_MTF_MIDTONES_DAY': 0.55,
        'IMAGE_DENOISE': '',
        'IMAGE_DENOISE_DAY': '',
        'IMAGE_DENOISE_STRENGTH': 3,
        'IMAGE_DENOISE_STRENGTH_DAY': 3,
        'BILATERAL_SIGMA_COLOR': 20,
        'BILATERAL_SIGMA_COLOR_DAY': 20,
        'BILATERAL_SIGMA_SPACE': 35,
        'BILATERAL_SIGMA_SPACE_DAY': 35,
        'WBR_FACTOR': 1.0,
        'WBG_FACTOR': 1.0,
        'WBB_FACTOR': 1.0,
        'WBR_FACTOR_DAY': 1.0,
        'WBG_FACTOR_DAY': 1.0,
        'WBB_FACTOR_DAY': 1.0,
        'AUTO_WB': False,
        'AUTO_WB_DAY': False,
        'WBR_MTF_MIDTONES': 0.5,
        'WBG_MTF_MIDTONES': 0.5,
        'WBB_MTF_MIDTONES': 0.5,
        'WBR_MTF_MIDTONES_DAY': 0.5,
        'WBG_MTF_MIDTONES_DAY': 0.5,
        'WBB_MTF_MIDTONES_DAY': 0.5,
        'SATURATION_FACTOR': 1.0,
        'SATURATION_FACTOR_DAY': 1.0,
        'GAMMA_CORRECTION': 1.0,
        'GAMMA_CORRECTION_DAY': 1.0,
        'SHARPEN_AMOUNT': 0.0,
        'SHARPEN_AMOUNT_DAY': 0.0,
        'CCD_COOLING': False,
        'CCD_COOLING_DAY': False,
        'CCD_TEMP': 15.0,
        'CCD_TEMP_DAY': 35.0,
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
        'WINDSPEED_DISPLAY': 'ms',
        'CCD_TEMP_SCRIPT': '',
        'GPS_ENABLE': False,
        'TARGET_ADU': 75,
        'TARGET_ADU_DAY': 75,
        'TARGET_ADU_DEV': 10,
        'TARGET_ADU_DEV_DAY': 20,
        'ADU_FOV_DIV': 4,
        'SQM_FOV_DIV': 4,
        'DETECT_STARS': True,
        'DETECT_STARS_THOLD': 0.6,
        'DETECT_STARS_METHOD': 'template',
        'DETECT_STARS_SEP_THOLD': 5.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_METEORS': False,
        'DETECT_METEORS_THOLD': 125,
        'DETECT_MASK': '',
        'DETECT_DRAW': False,
        'LOGO_OVERLAY': '',
        'HEALTHCHECK__DISK_USAGE': 90.0,
        'HEALTHCHECK__SWAP_USAGE': 90.0,
        'LOCATION_NAME': 'Adelaide',
        'LOCATION_LATITUDE': -34.9,
        'LOCATION_LONGITUDE': 138.6,
        'LOCATION_ELEVATION': 50,
        'TIMELAPSE_ENABLE': True,
        'TIMELAPSE_SKIP_FRAMES': 4,
        'TIMELAPSE__PRE_PROCESSOR': 'standard',
        'TIMELAPSE__PRE_PROCESSOR_DAY': 'standard',
        'TIMELAPSE__IMAGE_CIRCLE': 2000,
        'TIMELAPSE__KEOGRAM_RATIO': 0.15,
        'TIMELAPSE__PRE_SCALE': 50,
        'TIMELAPSE__FFMPEG_REPORT': False,
        'TIMELAPSE__USE_NIGHT_CONFIG': True,
        'CAPTURE_PAUSE': False,
        'DAYTIME_CAPTURE': True,
        'DAYTIME_CAPTURE_SAVE': True,
        'DAYTIME_TIMELAPSE': True,
        'DAYTIME_CONTRAST_ENHANCE': False,
        'NIGHT_CONTRAST_ENHANCE': False,
        'CONTRAST_ENHANCE_16BIT': False,
        'CLAHE_CLIPLIMIT': 3.0,
        'CLAHE_GRIDSIZE': 8,
        'NIGHT_SUN_ALT_DEG': -6.0,
        'NIGHT_MOONMODE_ALT_DEG': 5.0,
        'NIGHT_MOONMODE_PHASE': 50.0,
        'WEB_STATUS_TEMPLATE': '{date}',
        'WEB_EXTRA_TEXT': '',
        'WEBSOCKET_API_KEY': '',
        'WEB_NONLOCAL_IMAGES': False,
        'WEB_LOCAL_IMAGES_ADMIN': False,
        'IMAGE_STRETCH__CLASSNAME': '',
        'IMAGE_STRETCH__MODE1_GAMMA': 3.0,
        'IMAGE_STRETCH__MODE1_STDDEVS': 2.25,
        'IMAGE_STRETCH__MODE2_SHADOWS': 0.0,
        'IMAGE_STRETCH__MODE2_MIDTONES': 0.35,
        'IMAGE_STRETCH__MODE2_HIGHLIGHTS': 1.0,
        'IMAGE_STRETCH__MODE3_BLACK_CLIP': -2.8,
        'IMAGE_STRETCH__MODE3_SHADOWS': 0.0,
        'IMAGE_STRETCH__MODE3_MIDTONES': 0.25,
        'IMAGE_STRETCH__MODE3_HIGHLIGHTS': 1.0,
        'IMAGE_STRETCH__SPLIT': False,
        'IMAGE_STRETCH__MOONMODE': False,
        'IMAGE_STRETCH__DAYTIME': False,
        'KEOGRAM_ANGLE': 0.0,
        'KEOGRAM_H_SCALE': 100,
        'KEOGRAM_V_SCALE': 33,
        'KEOGRAM_CROP_TOP': 0,
        'KEOGRAM_CROP_BOTTOM': 0,
        'KEOGRAM_LABEL': True,
        'LONGTERM_KEOGRAM__ENABLE': True,
        'LONGTERM_KEOGRAM__OFFSET_X': 0,
        'LONGTERM_KEOGRAM__OFFSET_Y': 0,
        'LONGTERM_KEOGRAM__OPENCV_FONT_SCALE': 0.8,
        'LONGTERM_KEOGRAM__PIL_FONT_SIZE': 30,
        'LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE': '{month:%B %Y}',
        'REALTIME_KEOGRAM__MAX_ENTRIES': 1000,
        'REALTIME_KEOGRAM__SAVE_INTERVAL': 25,
        'REALTIME_KEOGRAM__LABEL': False,
        'STARTRAILS_SUN_ALT_THOLD': -15.0,
        'STARTRAILS_MOONMODE_THOLD': True,
        'STARTRAILS_MOON_ALT_THOLD': 91.0,
        'STARTRAILS_MOON_PHASE_THOLD': 101.0,
        'STARTRAILS_MAX_ADU': 65,
        'STARTRAILS_MASK_THOLD': 255,
        'STARTRAILS_PIXEL_THOLD': 1.0,
        'STARTRAILS_MIN_STARS': 0,
        'STARTRAILS_TIMELAPSE': True,
        'STARTRAILS_TIMELAPSE_MINFRAMES': 250,
        'STARTRAILS_USE_DB_DATA': True,
        'STARTRAILS__IMAGE_CIRCLE_MASK_ENABLE': False,
        'STARTRAILS__IMAGE_CIRCLE_MASK_DIAMETER': 3000,
        'STARTRAILS__IMAGE_CIRCLE_MASK_BLUR': 35,
        'STARTRAILS__IMAGE_CIRCLE_MASK_OPACITY': 100,
        'IMAGE_ASI676MC_REPAIR__ENABLE': False,
        'IMAGE_ASI676MC_REPAIR__EXCLUDE_ONLY': True,
        'IMAGE_ASI676MC_REPAIR__LOG_EVERY_FRAME': False,
        'IMAGE_ASI676MC_REPAIR__GALLERY_ENABLE': True,
        'IMAGE_ASI676MC_REPAIR__SAVE_DIAGNOSTIC_FITS': False,
        'IMAGE_ASI676MC_REPAIR__SAVE_PRECEDING_FITS': False,
        'IMAGE_ASI676MC_REPAIR__PURPLE_RATIO_THRESHOLD': 1.5,
        'IMAGE_ASI676MC_REPAIR__RED_SIDE_RATIO_THRESHOLD': 1.2,
        'IMAGE_ASI676MC_REPAIR__BLUE_SIDE_RATIO_THRESHOLD': 1.2,
        'IMAGE_ASI676MC_REPAIR__SAMPLE_STEP': 4,
        'IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD': 250,
        'IMAGE_ASI676MC_REPAIR__GAIN_R': 1.0,
        'IMAGE_ASI676MC_REPAIR__GAIN_G1': 1.0,
        'IMAGE_ASI676MC_REPAIR__GAIN_G2': 1.0,
        'IMAGE_ASI676MC_REPAIR__GAIN_B': 1.0,
        'IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_START_RATIO': 0.8,
        'IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_END_RATIO': 0.95,
        'IMAGE_ASI676MC_REPAIR__CHUNK_ROWS': 16,
        'IMAGE_CALIBRATE_DARK': True,
        'IMAGE_CALIBRATE_BPM': False,
        'IMAGE_CALIBRATE_FIX_HOLES': False,
        'IMAGE_CALIBRATE_HOLE_THOLD': 30,
        'IMAGE_CALIBRATE_MANUAL_OFFSET': 0,
        'IMAGE_SAVE_FITS_PRE_DARK': False,
        'PRIVACY_MODE': False,
        'IMAGE_EXIF_PRIVACY': False,
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION__JPG': 90,
        'IMAGE_FILE_COMPRESSION__PNG': 5,
        'IMAGE_FOLDER': '/tmp',
        'VARLIB_FOLDER': '/tmp',
        'IMAGE_LABEL_TEMPLATE': '{date}',
        'IMAGE_EXTRA_TEXT': '',
        'IMAGE_ROTATE': '',
        'IMAGE_ROTATE_ANGLE': 0,
        'IMAGE_ROTATE_KEEP_SIZE': False,
        'IMAGE_FLIP_V': True,
        'IMAGE_FLIP_H': True,
        'IMAGE_SCALE': 100,
        'IMAGE_COLORMAP': '',
        'IMAGE_CIRCLE_MASK__ENABLE': False,
        'IMAGE_CIRCLE_MASK__DIAMETER': 3000,
        'IMAGE_CIRCLE_MASK__OFFSET_X': 0,
        'IMAGE_CIRCLE_MASK__OFFSET_Y': 0,
        'IMAGE_CIRCLE_MASK__BLUR': 35,
        'IMAGE_CIRCLE_MASK__OPACITY': 100,
        'IMAGE_CIRCLE_MASK__OUTLINE': False,
        'IMAGE_CROP_IMAGE_CIRCLE': False,
        'FISH2PANO__ENABLE': True,
        'FISH2PANO__DIAMETER': 3000,
        'FISH2PANO__OFFSET_X': 0,
        'FISH2PANO__OFFSET_Y': 0,
        'FISH2PANO__ROTATE_ANGLE': -90,
        'FISH2PANO__SCALE': 0.5,
        'FISH2PANO__MODULUS': 2,
        'FISH2PANO__FLIP_H': False,
        'FISH2PANO__ENABLE_CARDINAL_DIRS': True,
        'FISH2PANO__DIRS_OFFSET_BOTTOM': 25,
        'FISH2PANO__OPENCV_FONT_SCALE': 0.8,
        'FISH2PANO__PIL_FONT_SIZE': 30,
        'IMAGE_SAVE_FITS': False,
        'IMAGE_SAVE_FITS_COMPRESSED': False,
        'IMAGE_SAVE_FITS_PERIOD': 7200,
        'NIGHT_GRAYSCALE': False,
        'DAYTIME_GRAYSCALE': False,
        'MOON_OVERLAY__ENABLE': True,
        'MOON_OVERLAY__X': -500,
        'MOON_OVERLAY__Y': -200,
        'MOON_OVERLAY__SCALE': 0.5,
        'MOON_OVERLAY__DARK_SIDE_SCALE': 0.4,
        'MOON_OVERLAY__FLIP_V': False,
        'MOON_OVERLAY__FLIP_H': False,
        'LIGHTGRAPH_OVERLAY__ENABLE': False,
        'LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT': 30,
        'LIGHTGRAPH_OVERLAY__GRAPH_BORDER': 3,
        'LIGHTGRAPH_OVERLAY__Y': 10,
        'LIGHTGRAPH_OVERLAY__OFFSET_X': 0,
        'LIGHTGRAPH_OVERLAY__SCALE': 1.0,
        'LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE': 8,
        'LIGHTGRAPH_OVERLAY__OPACITY': 100,
        'LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE': 20,
        'LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE': 0.5,
        'LIGHTGRAPH_OVERLAY__LABEL': True,
        'LIGHTGRAPH_OVERLAY__HOUR_LINES': True,
        'IMAGE_OVERLAY__ENABLE': False,
        'IMAGE_OVERLAY__LOAD_INTERVAL': 600,
        'IMAGE_OVERLAY__A_URL': '',
        'IMAGE_OVERLAY__A_IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_OVERLAY__A_WIDTH': 250,
        'IMAGE_OVERLAY__A_HEIGHT': 250,
        'IMAGE_OVERLAY__A_X': 300,
        'IMAGE_OVERLAY__A_Y': -300,
        'IMAGE_OVERLAY__A_USERNAME': '',
        'IMAGE_OVERLAY__A_PASSWORD': '',
        'IMAGE_EXPORT_RAW': '',
        'IMAGE_EXPORT_FOLDER': '/tmp',
        'IMAGE_EXPORT_FLIP_V': False,
        'IMAGE_EXPORT_FLIP_H': False,
        'IMAGE_STACK_METHOD': 'maximum',
        'IMAGE_STACK_COUNT': 1,
        'IMAGE_STACK_ALIGN': False,
        'IMAGE_ALIGN_DETECTSIGMA': 5,
        'IMAGE_ALIGN_POINTS': 50,
        'IMAGE_ALIGN_SOURCEMINAREA': 10,
        'IMAGE_STACK_SPLIT': False,
        'IMAGE_STACK_MOONMODE': False,
        'IMAGE_STACK_DAY': False,
        'IMAGE_QUEUE_MAX': 3,
        'IMAGE_QUEUE_MIN': 1,
        'IMAGE_QUEUE_BACKOFF': 0.5,
        'IMAGE_SAVE_HOOK_PRE': '',
        'IMAGE_SAVE_HOOK_POST': '',
        'IMAGE_SAVE_HOOK_TIMEOUT': 5,
        'CAPTURE_HOOK_PRE': '',
        'CAPTURE_HOOK_TIMEOUT': 5,
        'BACKUP_DB_PERIOD_DAYS': 7,
        'IMAGE_EXPIRE_DAYS': 10,
        'IMAGE_RAW_EXPIRE_DAYS': 10,
        'IMAGE_FITS_EXPIRE_DAYS': 10,
        'TIMELAPSE_EXPIRE_DAYS': 365,
        'TIMELAPSE_OVERWRITE': False,
        'FFMPEG_FRAMERATE': 25,
        'FFMPEG_FRAMERATE_DAY': 25,
        'FFMPEG_BITRATE': '5000k',
        'FFMPEG_BITRATE_DAY': '5000k',
        'FFMPEG_VFSCALE': '',
        'FFMPEG_VFSCALE_DAY': '',
        'FFMPEG_VFSCALE_STARTRAIL': '',
        'FFMPEG_CODEC': 'libx264',
        'FFMPEG_EXTRA_OPTIONS': '-level 3.1',
        'FFMPEG_EXTRA_OPTIONS_DAY': '-level 3.1',
        'IMAGE_LABEL_SYSTEM': 'pillow',
        'TEXT_PROPERTIES__FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
        'TEXT_PROPERTIES__FONT_SCALE': 0.8,
        'TEXT_PROPERTIES__FONT_THICKNESS': 1,
        'TEXT_PROPERTIES__FONT_OUTLINE': True,
        'TEXT_PROPERTIES__FONT_HEIGHT': 30,
        'TEXT_PROPERTIES__FONT_X': 15,
        'TEXT_PROPERTIES__FONT_Y': 30,
        'TEXT_PROPERTIES__PIL_FONT_FILE': 'fonts-freefont-ttf/FreeSans.ttf',
        'TEXT_PROPERTIES__PIL_FONT_CUSTOM': '',
        'TEXT_PROPERTIES__PIL_FONT_SIZE': 30,
        'CARDINAL_DIRS__ENABLE': True,
        'CARDINAL_DIRS__SWAP_NS': False,
        'CARDINAL_DIRS__SWAP_EW': False,
        'CARDINAL_DIRS__CHAR_NORTH': 'N',
        'CARDINAL_DIRS__CHAR_EAST': 'E',
        'CARDINAL_DIRS__CHAR_WEST': 'W',
        'CARDINAL_DIRS__CHAR_SOUTH': 'S',
        'CARDINAL_DIRS__DIAMETER': 3000,
        'CARDINAL_DIRS__OFFSET_X': 0,
        'CARDINAL_DIRS__OFFSET_Y': 0,
        'CARDINAL_DIRS__OFFSET_TOP': 15,
        'CARDINAL_DIRS__OFFSET_LEFT': 15,
        'CARDINAL_DIRS__OFFSET_RIGHT': 15,
        'CARDINAL_DIRS__OFFSET_BOTTOM': 15,
        'CARDINAL_DIRS__OPENCV_FONT_SCALE': 0.5,
        'CARDINAL_DIRS__PIL_FONT_SIZE': 20,
        'CARDINAL_DIRS__OUTLINE_CIRCLE': False,
        'ORB_PROPERTIES__MODE': 'ha',
        'ORB_PROPERTIES__RADIUS': 9,
        'ORB_PROPERTIES__AZ_OFFSET': 0.0,
        'ORB_PROPERTIES__RETROGRADE': False,
        'IMAGE_BORDER__TOP': 0,
        'IMAGE_BORDER__LEFT': 0,
        'IMAGE_BORDER__RIGHT': 0,
        'IMAGE_BORDER__BOTTOM': 0,
        'UPLOAD_WORKERS': 2,
        'FILETRANSFER__CLASSNAME': 'pycurl_sftp',
        'FILETRANSFER__HOST': '',
        'FILETRANSFER__PORT': 0,
        'FILETRANSFER__USERNAME': '',
        'FILETRANSFER__PASSWORD': '',
        'FILETRANSFER__PRIVATE_KEY': '',
        'FILETRANSFER__PUBLIC_KEY': '',
        'FILETRANSFER__CONNECT_TIMEOUT': 10.0,
        'FILETRANSFER__TIMEOUT': 60.0,
        'FILETRANSFER__CERT_BYPASS': True,
        'FILETRANSFER__ATOMIC_TRANSFERS': False,
        'FILETRANSFER__FORCE_IPV4': False,
        'FILETRANSFER__FORCE_IPV6': False,
        'FILETRANSFER__REMOTE_IMAGE_NAME': 'image.jpg',
        'FILETRANSFER__REMOTE_IMAGE_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_PANORAMA_NAME': 'pano.jpg',
        'FILETRANSFER__REMOTE_PANORAMA_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_METADATA_NAME': 'meta.json',
        'FILETRANSFER__REMOTE_METADATA_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_RAW_NAME': 'raw.raw',
        'FILETRANSFER__REMOTE_RAW_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_FITS_NAME': 'fits.fits',
        'FILETRANSFER__REMOTE_FITS_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_VIDEO_NAME': 'video.mp4',
        'FILETRANSFER__REMOTE_VIDEO_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_MINI_VIDEO_NAME': 'minivideo.mp4',
        'FILETRANSFER__REMOTE_MINI_VIDEO_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_KEOGRAM_NAME': 'keogram.jpg',
        'FILETRANSFER__REMOTE_KEOGRAM_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_STARTRAIL_NAME': 'startrail.jpg',
        'FILETRANSFER__REMOTE_STARTRAIL_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_STARTRAIL_VIDEO_NAME': 'startrail.mp4',
        'FILETRANSFER__REMOTE_STARTRAIL_VIDEO_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_PANORAMA_VIDEO_NAME': 'panovideo.mp4',
        'FILETRANSFER__REMOTE_PANORAMA_VIDEO_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_REALTIME_KEOGRAM_NAME': 'realtime.jpg',
        'FILETRANSFER__REMOTE_REALTIME_KEOGRAM_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_LATEST_FOLDER': '/upload',
        'FILETRANSFER__REMOTE_DB_BACKUP_FOLDER': '/upload',
        'FILETRANSFER__UPLOAD_IMAGE': 0,
        'FILETRANSFER__UPLOAD_PANORAMA': 0,
        'FILETRANSFER__UPLOAD_METADATA': False,
        'FILETRANSFER__UPLOAD_VIDEO': False,
        'FILETRANSFER__UPLOAD_MINI_VIDEO': False,
        'FILETRANSFER__UPLOAD_RAW': False,
        'FILETRANSFER__UPLOAD_FITS': False,
        'FILETRANSFER__UPLOAD_KEOGRAM': False,
        'FILETRANSFER__UPLOAD_STARTRAIL': False,
        'FILETRANSFER__UPLOAD_STARTRAIL_VIDEO': False,
        'FILETRANSFER__UPLOAD_PANORAMA_VIDEO': False,
        'FILETRANSFER__UPLOAD_REALTIME_KEOGRAM': 0,
        'FILETRANSFER__UPLOAD_ENDOFNIGHT': False,
        'FILETRANSFER__UPLOAD_LATEST_IMAGE': False,
        'FILETRANSFER__UPLOAD_LATEST_PANORAMA': False,
        'FILETRANSFER__UPLOAD_LATEST_RAW': False,
        'FILETRANSFER__UPLOAD_LATEST_VIDEO': False,
        'FILETRANSFER__UPLOAD_DB_BACKUP': False,
        'S3UPLOAD__CLASSNAME': 'boto3_s3',
        'S3UPLOAD__ENABLE': False,
        'S3UPLOAD__ACCESS_KEY': '',
        'S3UPLOAD__SECRET_KEY': '',
        'S3UPLOAD__CREDS_FILE': '',
        'S3UPLOAD__BUCKET': 'mybucket',
        'S3UPLOAD__REGION': 'us-east-1',
        'S3UPLOAD__NAMESPACE': '',
        'S3UPLOAD__HOST': 'amazonaws.com',
        'S3UPLOAD__ENDPOINT_URL': '',
        'S3UPLOAD__PORT': 0,
        'S3UPLOAD__CONNECT_TIMEOUT': 10.0,
        'S3UPLOAD__TIMEOUT': 60.0,
        'S3UPLOAD__URL_TEMPLATE': 'https://example.com/{filename}',
        'S3UPLOAD__STORAGE_CLASS': 'STANDARD',
        'S3UPLOAD__ACL': '',
        'S3UPLOAD__TLS': True,
        'S3UPLOAD__CERT_BYPASS': False,
        'S3UPLOAD__UPLOAD_FITS': False,
        'S3UPLOAD__UPLOAD_RAW': False,
        'MQTTPUBLISH__ENABLE': False,
        'MQTTPUBLISH__TRANSPORT': 'tcp',
        'MQTTPUBLISH__PROTOCOL': 'MQTTv5',
        'MQTTPUBLISH__HOST': 'localhost',
        'MQTTPUBLISH__PORT': 8883,
        'MQTTPUBLISH__USERNAME': 'user',
        'MQTTPUBLISH__PASSWORD': '',
        'MQTTPUBLISH__BASE_TOPIC': 'indi-allsky',
        'MQTTPUBLISH__QOS': 0,
        'MQTTPUBLISH__TLS': True,
        'MQTTPUBLISH__CERT_BYPASS': True,
        'MQTTPUBLISH__PUBLISH_IMAGE': True,
        'SYNCAPI__ENABLE': False,
        'SYNCAPI__BASEURL': 'https://example.com',
        'SYNCAPI__USERNAME': '',
        'SYNCAPI__APIKEY': '',
        'SYNCAPI__CERT_BYPASS': False,
        'SYNCAPI__POST_S3': False,
        'SYNCAPI__EMPTY_FILE': False,
        'SYNCAPI__UPLOAD_IMAGE': 1,
        'SYNCAPI__UPLOAD_PANORAMA': 1,
        'SYNCAPI__CONNECT_TIMEOUT': 10.0,
        'SYNCAPI__TIMEOUT': 60.0,
        'ALLSKYMAP__ENABLE': False,
        'ALLSKYMAP__API_URL': 'https://allsky-map.com',
        'ALLSKYMAP__API_KEY': '',
        'ALLSKYMAP__CAMERA_NAME': '',
        'ALLSKYMAP__CAMERA_OWNER': '',
        'ALLSKYMAP__WEBSITE_URL': '',
        'ALLSKYMAP__MAP_LATITUDE': -34.9,
        'ALLSKYMAP__MAP_LONGITUDE': 138.6,
        'ALLSKYMAP__UPLOAD_IMAGE': True,
        'ALLSKYMAP__INTERVAL': 10,
        'YOUTUBE__ENABLE': False,
        'YOUTUBE__SECRETS_FILE': '',
        'YOUTUBE__PRIVACY_STATUS': 'unlisted',
        'YOUTUBE__TITLE_TEMPLATE': '{date}',
        'YOUTUBE__DESCRIPTION_TEMPLATE': '',
        'YOUTUBE__CATEGORY': 22,
        'YOUTUBE__UPLOAD_VIDEO': False,
        'YOUTUBE__UPLOAD_MINI_VIDEO': False,
        'YOUTUBE__UPLOAD_STARTRAIL_VIDEO': False,
        'YOUTUBE__UPLOAD_PANORAMA_VIDEO': False,
        'FITSHEADERS__0__KEY': 'INSTRUME',
        'FITSHEADERS__0__VAL': 'indi-allsky',
        'FITSHEADERS__1__KEY': 'OBSERVER',
        'FITSHEADERS__1__VAL': 'Admin',
        'FITSHEADERS__2__KEY': 'SITE',
        'FITSHEADERS__2__VAL': 'Observatory',
        'FITSHEADERS__3__KEY': 'OBJECT',
        'FITSHEADERS__3__VAL': 'Sky',
        'FITSHEADERS__4__KEY': 'NOTES',
        'FITSHEADERS__4__VAL': 'Test',
        'LIBCAMERA__IMAGE_FILE_TYPE': 'jpg',
        'LIBCAMERA__IMAGE_FILE_TYPE_DAY': 'jpg',
        'LIBCAMERA__IMMEDIATE': True,
        'LIBCAMERA__IMMEDIATE_DAY': True,
        'LIBCAMERA__AWB': 'auto',
        'LIBCAMERA__AWB_DAY': 'auto',
        'LIBCAMERA__AWB_ENABLE': True,
        'LIBCAMERA__AWB_ENABLE_DAY': True,
        'LIBCAMERA__CCM_DISABLE': False,
        'LIBCAMERA__CCM_DISABLE_DAY': False,
        'LIBCAMERA__CAMERA_ID': 0,
        'LIBCAMERA__EXTRA_OPTIONS': '',
        'LIBCAMERA__EXTRA_OPTIONS_DAY': '',
        'LIBCAMERA__MQTT_TRANSPORT': 'tcp',
        'LIBCAMERA__MQTT_PROTOCOL': 'MQTTv5',
        'LIBCAMERA__MQTT_HOST': 'localhost',
        'LIBCAMERA__MQTT_PORT': 8883,
        'LIBCAMERA__MQTT_USERNAME': 'user',
        'LIBCAMERA__MQTT_PASSWORD': '',
        'LIBCAMERA__MQTT_QOS': 0,
        'LIBCAMERA__MQTT_TLS': True,
        'LIBCAMERA__MQTT_CERT_BYPASS': True,
        'LIBCAMERA__MQTT_EXPOSURE_TOPIC': 'topic1',
        'LIBCAMERA__MQTT_IMAGE_TOPIC': 'topic2',
        'LIBCAMERA__MQTT_METADATA_TOPIC': 'topic3',
        'PYCURL_CAMERA__URL': '',
        'PYCURL_CAMERA__IMAGE_FILE_TYPE': 'jpg',
        'PYCURL_CAMERA__USERNAME': '',
        'PYCURL_CAMERA__PASSWORD': '',
        'ACCUM_CAMERA__SUB_EXPOSURE_MAX': 1.0,
        'ACCUM_CAMERA__EVEN_EXPOSURES': True,
        'ACCUM_CAMERA__CLAMP_16BIT': False,
        'TEST_CAMERA__WIDTH': 4056,
        'TEST_CAMERA__HEIGHT': 3040,
        'TEST_CAMERA__IMAGE_CIRCLE_DIAMETER': 3500,
        'TEST_CAMERA__IMAGE_CIRCLE_OFFSET_X': 0,
        'TEST_CAMERA__IMAGE_CIRCLE_OFFSET_Y': 0,
        'TEST_CAMERA__ROTATING_STAR_COUNT': 30000,
        'TEST_CAMERA__ROTATING_STAR_FACTOR': 1.0,
        'TEST_CAMERA__BUBBLE_COUNT': 1000,
        'VIRTUALSKY__MAGNITUDE': 6.0,
        'VIRTUALSKY__CONSTELLATIONS': True,
        'VIRTUALSKY__CONSTELLATIONLABELS': False,
        'VIRTUALSKY__SHOWSTARS': True,
        'VIRTUALSKY__SHOWSTARLABELS': True,
        'VIRTUALSKY__SHOWPLANETS': True,
        'VIRTUALSKY__SHOWPLANETLABELS': True,
        'VIRTUALSKY__IMAGE_CIRCLE_DIAMETER': 3500,
        'VIRTUALSKY__LATITUDE_OFFSET': 0.0,
        'VIRTUALSKY__LONGITUDE_OFFSET': 0.0,
        'VIRTUALSKY__OFFSET_X': 0,
        'VIRTUALSKY__OFFSET_Y': 0,
        'CIRCULAR_DISPLAY__ENABLE': False,
        'CIRCULAR_DISPLAY__RESOLUTION': 800,
        'CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER': 3500,
        'FOCUSER__CLASSNAME': '',
        'FOCUSER__GPIO_PIN_1': 'D17',
        'FOCUSER__GPIO_PIN_2': 'D18',
        'FOCUSER__GPIO_PIN_3': 'D27',
        'FOCUSER__GPIO_PIN_4': 'D22',
        'FOCUSER__I2C_ADDRESS': '0x60',
        'DEW_HEATER__CLASSNAME': '',
        'DEW_HEATER__I2C_ADDRESS': '0x10',
        'DEW_HEATER__PIN_1': 'D12',
        'DEW_HEATER__INVERT_OUTPUT': False,
        'DEW_HEATER__ENABLE_DAY': False,
        'DEW_HEATER__LEVEL_DEF': 100,
        'DEW_HEATER__THOLD_ENABLE': False,
        'DEW_HEATER__MANUAL_TARGET': 0.0,
        'DEW_HEATER__TEMP_USER_VAR_SLOT': 'sensor_user_10',
        'DEW_HEATER__DEWPOINT_USER_VAR_SLOT': 'sensor_user_2',
        'DEW_HEATER__LEVEL_LOW': 33,
        'DEW_HEATER__LEVEL_MED': 66,
        'DEW_HEATER__LEVEL_HIGH': 100,
        'DEW_HEATER__THOLD_DIFF_LOW': 15,
        'DEW_HEATER__THOLD_DIFF_MED': 10,
        'DEW_HEATER__THOLD_DIFF_HIGH': 5,
        'DEW_HEATER__HOLD_SECONDS': 0,
        'DEW_HEATER__PWM_FREQUENCY': 500,
        'FAN__CLASSNAME': '',
        'FAN__I2C_ADDRESS': '0x11',
        'FAN__PIN_1': 'D13',
        'FAN__INVERT_OUTPUT': False,
        'FAN__ENABLE_NIGHT': False,
        'FAN__LEVEL_DEF': 100,
        'FAN__THOLD_ENABLE': False,
        'FAN__TARGET': 30.0,
        'FAN__TEMP_USER_VAR_SLOT': 'sensor_user_10',
        'FAN__LEVEL_LOW': 33,
        'FAN__LEVEL_MED': 66,
        'FAN__LEVEL_HIGH': 100,
        'FAN__THOLD_DIFF_LOW': -10,
        'FAN__THOLD_DIFF_MED': -5,
        'FAN__THOLD_DIFF_HIGH': 0,
        'FAN__HOLD_SECONDS': 0,
        'FAN__PWM_FREQUENCY': 500,
        'GENERIC_GPIO__A_CLASSNAME': '',
        'GENERIC_GPIO__A_I2C_ADDRESS': '0x12',
        'GENERIC_GPIO__A_PIN_1': 'D21',
        'GENERIC_GPIO__A_INVERT_OUTPUT': False,
        'MANUAL_GPIO__A_CLASSNAME': '',
        'MANUAL_GPIO__A_PIN_1': '21',
        'MANUAL_GPIO__A_PIN_2': '25',
        'MANUAL_GPIO__A_PIN_3': '16',
        'DEVICE__MQTT_TRANSPORT': 'tcp',
        'DEVICE__MQTT_PROTOCOL': 'MQTTv5',
        'DEVICE__MQTT_HOST': 'localhost',
        'DEVICE__MQTT_PORT': 8883,
        'DEVICE__MQTT_USERNAME': 'indi-allsky',
        'DEVICE__MQTT_PASSWORD': '',
        'DEVICE__MQTT_QOS': 0,
        'DEVICE__MQTT_TLS': True,
        'DEVICE__MQTT_CERT_BYPASS': True,
        'TEMP_SENSOR__A_CLASSNAME': '',
        'TEMP_SENSOR__A_LABEL': 'Sensor A',
        'TEMP_SENSOR__A_PIN_1': 'D5',
        'TEMP_SENSOR__A_PIN_2': '',
        'TEMP_SENSOR__A_I2C_ADDRESS': '0x77',
        'TEMP_SENSOR__A_USER_VAR_SLOT': 'sensor_user_10',
        'TEMP_SENSOR__A_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__B_CLASSNAME': '',
        'TEMP_SENSOR__B_LABEL': 'Sensor B',
        'TEMP_SENSOR__B_PIN_1': 'D6',
        'TEMP_SENSOR__B_PIN_2': '',
        'TEMP_SENSOR__B_I2C_ADDRESS': '0x76',
        'TEMP_SENSOR__B_USER_VAR_SLOT': 'sensor_user_20',
        'TEMP_SENSOR__B_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__C_CLASSNAME': '',
        'TEMP_SENSOR__C_LABEL': 'Sensor C',
        'TEMP_SENSOR__C_PIN_1': 'D16',
        'TEMP_SENSOR__C_PIN_2': '',
        'TEMP_SENSOR__C_I2C_ADDRESS': '0x40',
        'TEMP_SENSOR__C_USER_VAR_SLOT': 'sensor_user_30',
        'TEMP_SENSOR__C_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__D_CLASSNAME': '',
        'TEMP_SENSOR__D_LABEL': 'Sensor D',
        'TEMP_SENSOR__D_PIN_1': 'D26',
        'TEMP_SENSOR__D_PIN_2': '',
        'TEMP_SENSOR__D_I2C_ADDRESS': '0x50',
        'TEMP_SENSOR__D_USER_VAR_SLOT': 'sensor_user_40',
        'TEMP_SENSOR__D_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__E_CLASSNAME': '',
        'TEMP_SENSOR__E_LABEL': 'Sensor E',
        'TEMP_SENSOR__E_PIN_1': 'D25',
        'TEMP_SENSOR__E_PIN_2': '',
        'TEMP_SENSOR__E_I2C_ADDRESS': '0x51',
        'TEMP_SENSOR__E_USER_VAR_SLOT': 'sensor_user_50',
        'TEMP_SENSOR__E_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__F_CLASSNAME': '',
        'TEMP_SENSOR__F_LABEL': 'Sensor F',
        'TEMP_SENSOR__F_PIN_1': 'D27',
        'TEMP_SENSOR__F_PIN_2': '',
        'TEMP_SENSOR__F_I2C_ADDRESS': '0x52',
        'TEMP_SENSOR__F_USER_VAR_SLOT': 'sensor_user_55',
        'TEMP_SENSOR__F_TITLE_TEMPLATE': '{temp}',
        'TEMP_SENSOR__FC37_ACTIVE_LOW': True,
        'TEMP_SENSOR__OPENWEATHERMAP_APIKEY': '',
        'TEMP_SENSOR__WUNDERGROUND_APIKEY': '',
        'TEMP_SENSOR__ASTROSPHERIC_APIKEY': '',
        'TEMP_SENSOR__AMBIENTWEATHER_APIKEY': '',
        'TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY': '',
        'TEMP_SENSOR__AMBIENTWEATHER_MACADDRESS': '',
        'TEMP_SENSOR__ECOWITT_APIKEY': '',
        'TEMP_SENSOR__ECOWITT_APPLICATIONKEY': '',
        'TEMP_SENSOR__ECOWITT_MACADDRESS': '',
        'TEMP_SENSOR__MQTT_TRANSPORT': 'tcp',
        'TEMP_SENSOR__MQTT_PROTOCOL': 'MQTTv5',
        'TEMP_SENSOR__MQTT_HOST': 'localhost',
        'TEMP_SENSOR__MQTT_PORT': 8883,
        'TEMP_SENSOR__MQTT_USERNAME': 'indi-allsky',
        'TEMP_SENSOR__MQTT_PASSWORD': '',
        'TEMP_SENSOR__MQTT_TLS': True,
        'TEMP_SENSOR__MQTT_CERT_BYPASS': True,
        'TEMP_SENSOR__DHT_USE_PULSEIO': False,
        'TEMP_SENSOR__SHT3X_HEATER_NIGHT': False,
        'TEMP_SENSOR__SHT3X_HEATER_DAY': False,
        'TEMP_SENSOR__SHT4X_MODE_NIGHT': 'NOHEAT_HIGHPRECISION',
        'TEMP_SENSOR__SHT4X_MODE_DAY': 'NOHEAT_HIGHPRECISION',
        'TEMP_SENSOR__SI7021_HEATER_LEVEL_NIGHT': -1,
        'TEMP_SENSOR__SI7021_HEATER_LEVEL_DAY': -1,
        'TEMP_SENSOR__HTU31D_HEATER_NIGHT': False,
        'TEMP_SENSOR__HTU31D_HEATER_DAY': False,
        'TEMP_SENSOR__HDC302X_HEATER_NIGHT': 'OFF',
        'TEMP_SENSOR__HDC302X_HEATER_DAY': 'OFF',
        'TEMP_SENSOR__TSL2561_GAIN_NIGHT': 1,
        'TEMP_SENSOR__TSL2561_GAIN_DAY': 0,
        'TEMP_SENSOR__TSL2561_INT_NIGHT': 1,
        'TEMP_SENSOR__TSL2561_INT_DAY': 1,
        'TEMP_SENSOR__TSL2561_DISABLE_DAY': False,
        'TEMP_SENSOR__TSL2591_GAIN_NIGHT': 'GAIN_MED',
        'TEMP_SENSOR__TSL2591_GAIN_DAY': 'GAIN_LOW',
        'TEMP_SENSOR__TSL2591_INT_NIGHT': 'INTEGRATIONTIME_100MS',
        'TEMP_SENSOR__TSL2591_INT_DAY': 'INTEGRATIONTIME_100MS',
        'TEMP_SENSOR__TSL2591_DISABLE_DAY': False,
        'TEMP_SENSOR__VEML7700_GAIN_NIGHT': 'ALS_GAIN_1',
        'TEMP_SENSOR__VEML7700_GAIN_DAY': 'ALS_GAIN_1_8',
        'TEMP_SENSOR__VEML7700_INT_NIGHT': 'ALS_100MS',
        'TEMP_SENSOR__VEML7700_INT_DAY': 'ALS_100MS',
        'TEMP_SENSOR__SI1145_VIS_GAIN_NIGHT': 'GAIN_ADC_CLOCK_DIV_32',
        'TEMP_SENSOR__SI1145_VIS_GAIN_DAY': 'GAIN_ADC_CLOCK_DIV_1',
        'TEMP_SENSOR__SI1145_IR_GAIN_NIGHT': 'GAIN_ADC_CLOCK_DIV_32',
        'TEMP_SENSOR__SI1145_IR_GAIN_DAY': 'GAIN_ADC_CLOCK_DIV_1',
        'TEMP_SENSOR__SI1145_VIS_RANGE_HIGH_NIGHT': False,
        'TEMP_SENSOR__SI1145_IR_RANGE_HIGH_NIGHT': False,
        'TEMP_SENSOR__SI1145_VIS_RANGE_HIGH_DAY': True,
        'TEMP_SENSOR__SI1145_IR_RANGE_HIGH_DAY': True,
        'TEMP_SENSOR__LTR390_GAIN_NIGHT': 'GAIN_9X',
        'TEMP_SENSOR__LTR390_GAIN_DAY': 'GAIN_1X',
        'TEMP_SENSOR__INA3221_CH1_ENABLE': True,
        'TEMP_SENSOR__INA3221_CH2_ENABLE': True,
        'TEMP_SENSOR__INA3221_CH3_ENABLE': True,
        'TEMP_SENSOR__AS3935_OUTDOOR_MODE': True,
        'TEMP_SENSOR__AS3935_MASK_DISTURBER': False,
        'TEMP_SENSOR__AS3935_NOISE_LEVEL': 2,
        'TEMP_SENSOR__AS3935_SPIKE_REJECTION': 2,
        'TEMP_SENSOR__LUX_MAGNITUDE_OFFSET': 26.0,
        'CHARTS__CUSTOM_SLOT_1': 'sensor_user_10',
        'CHARTS__CUSTOM_SLOT_1_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_2': 'sensor_user_11',
        'CHARTS__CUSTOM_SLOT_2_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_3': 'sensor_user_12',
        'CHARTS__CUSTOM_SLOT_3_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_4': 'sensor_user_13',
        'CHARTS__CUSTOM_SLOT_4_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_5': 'sensor_user_14',
        'CHARTS__CUSTOM_SLOT_5_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_6': 'sensor_user_15',
        'CHARTS__CUSTOM_SLOT_6_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_7': 'sensor_user_16',
        'CHARTS__CUSTOM_SLOT_7_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_8': 'sensor_user_14',
        'CHARTS__CUSTOM_SLOT_8_MIN': 0.0,
        'CHARTS__CUSTOM_SLOT_9': 'sensor_user_15',
        'CHARTS__CUSTOM_SLOT_9_MIN': 0.0,
        'ADSB__ENABLE': False,
        'ADSB__DUMP1090_URL': 'https://localhost/skyaware/data/aircraft.json',
        'ADSB__USERNAME': '',
        'ADSB__PASSWORD': '',
        'ADSB__CERT_BYPASS': True,
        'ADSB__ALT_DEG_MIN': 20.0,
        'ADSB__LABEL_ENABLE': True,
        'ADSB__LABEL_LIMIT': 10,
        'ADSB__AIRCRAFT_LABEL_TEMPLATE': '{callsign}',
        'ADSB__IMAGE_LABEL_TEMPLATE_PREFIX': 'ADSB:',
        'SATELLITE_TRACK__ENABLE': False,
        'SATELLITE_TRACK__DAYTIME_TRACK': False,
        'SATELLITE_TRACK__ALT_DEG_MIN': 20.0,
        'SATELLITE_TRACK__LABEL_ENABLE': True,
        'SATELLITE_TRACK__LABEL_LIMIT': 10,
        'SATELLITE_TRACK__SAT_LABEL_TEMPLATE': '{name}',
        'SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX': 'SAT:',
        'RELOAD_ON_SAVE': True,
        'CONFIG_NOTE': 'Updating configuration',
        'ENCRYPT_PASSWORDS': False,
        'ADU_ROI_X1': 0,
        'ADU_ROI_Y1': 0,
        'ADU_ROI_X2': 0,
        'ADU_ROI_Y2': 0,
        'SQM_ROI_X1': 0,
        'SQM_ROI_Y1': 0,
        'SQM_ROI_X2': 0,
        'SQM_ROI_Y2': 0,
        'IMAGE_CROP_ROI_X1': 0,
        'IMAGE_CROP_ROI_Y1': 0,
        'IMAGE_CROP_ROI_X2': 0,
        'IMAGE_CROP_ROI_Y2': 0,
        'TEXT_PROPERTIES__FONT_COLOR': '200,200,200',
        'CARDINAL_DIRS__FONT_COLOR': '200,0,0',
        'ORB_PROPERTIES__SUN_COLOR': '200,200,100',
        'ORB_PROPERTIES__MOON_COLOR': '128,128,128',
        'IMAGE_BORDER__COLOR': '0,0,0',
        'LIGHTGRAPH_OVERLAY__DAY_COLOR': '150,150,150',
        'LIGHTGRAPH_OVERLAY__DUSK_COLOR': '200,100,60',
        'LIGHTGRAPH_OVERLAY__NIGHT_COLOR': '30,30,30',
        'LIGHTGRAPH_OVERLAY__MOONMODE_COLOR': '50,50,50',
        'LIGHTGRAPH_OVERLAY__HOUR_COLOR': '100,15,15',
        'LIGHTGRAPH_OVERLAY__BORDER_COLOR': '1,1,1',
        'LIGHTGRAPH_OVERLAY__NOW_COLOR': '120,120,200',
        'LIGHTGRAPH_OVERLAY__FONT_COLOR': '150,150,150',
        'YOUTUBE__TAGS_STR': 'sky, astrophotography',
        'FILETRANSFER__LIBCURL_OPTIONS': '{"VERBOSE": 0}',
        'INDI_CONFIG_DEFAULTS': '{}',
        'INDI_CONFIG_DAY': '{}',
    }


def test_ajax_config_view_permissions_and_validation(flask_app, config_db):
    client = flask_app.test_client()

    # Permission check when LOGIN_DISABLED is False (unauthenticated redirect)
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': False}):
        res = client.post('/indi-allsky/ajax/config', json=get_base_payload())
        assert res.status_code == 302

    # Validation failure with invalid form data
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        bad_payload = get_base_payload()
        bad_payload['CAMERA_INTERFACE'] = 'invalid_choice'
        res_val = client.post('/indi-allsky/ajax/config', json=bad_payload)
        assert res_val.status_code == 400
        data = res_val.get_json()
        assert 'CAMERA_INTERFACE' in data or 'form_global' in data


def test_ajax_config_view_asi676mc_check(flask_app, config_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views._visible_asi676mc_cameras', return_value=[]):
            with patch('indi_allsky.flask.views.current_user') as mock_user:
                mock_user.is_admin = True
                payload = get_base_payload()
                payload['IMAGE_ASI676MC_REPAIR__ENABLE'] = True
                payload['IMAGE_LABEL_TEMPLATE'] = 'AllSky'
                payload['WEB_STATUS_TEMPLATE'] = 'AllSky'
                payload['YOUTUBE__TITLE_TEMPLATE'] = 'AllSky'
                payload['S3UPLOAD__URL_TEMPLATE'] = 'https://example.com/file'
                payload['ADSB__AIRCRAFT_LABEL_TEMPLATE'] = 'Aircraft'
                payload['SATELLITE_TRACK__SAT_LABEL_TEMPLATE'] = 'Satellite'
                payload['TEMP_SENSOR__A_TITLE_TEMPLATE'] = 'Temp'
                payload['TEMP_SENSOR__B_TITLE_TEMPLATE'] = 'Temp'
                payload['TEMP_SENSOR__C_TITLE_TEMPLATE'] = 'Temp'
                payload['TEMP_SENSOR__D_TITLE_TEMPLATE'] = 'Temp'
                payload['TEMP_SENSOR__E_TITLE_TEMPLATE'] = 'Temp'
                payload['TEMP_SENSOR__F_TITLE_TEMPLATE'] = 'Temp'
                res = client.post('/indi-allsky/ajax/config?camera_id=1', json=payload)
                assert res.status_code == 400
                data = res.get_json()
                assert 'IMAGE_ASI676MC_REPAIR__ENABLE' in data


def test_ajax_config_view_success_and_reload(flask_app, config_db):
    client = flask_app.test_client()
    valid_payload = get_base_payload()
    valid_payload['IMAGE_LABEL_TEMPLATE'] = 'AllSky'
    valid_payload['WEB_STATUS_TEMPLATE'] = 'AllSky'
    valid_payload['YOUTUBE__TITLE_TEMPLATE'] = 'AllSky'
    valid_payload['S3UPLOAD__URL_TEMPLATE'] = 'https://example.com/file'
    valid_payload['ADSB__AIRCRAFT_LABEL_TEMPLATE'] = 'Aircraft'
    valid_payload['SATELLITE_TRACK__SAT_LABEL_TEMPLATE'] = 'Satellite'
    valid_payload['TEMP_SENSOR__A_TITLE_TEMPLATE'] = 'Temp'
    valid_payload['TEMP_SENSOR__B_TITLE_TEMPLATE'] = 'Temp'
    valid_payload['TEMP_SENSOR__C_TITLE_TEMPLATE'] = 'Temp'
    valid_payload['TEMP_SENSOR__D_TITLE_TEMPLATE'] = 'Temp'
    valid_payload['TEMP_SENSOR__E_TITLE_TEMPLATE'] = 'Temp'
    valid_payload['TEMP_SENSOR__F_TITLE_TEMPLATE'] = 'Temp'

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.current_user') as mock_user:
            mock_user.is_admin = True
            mock_user.username = 'admin'
            # Mock send_allsky_map_ping success
            with patch('indi_allsky.allsky_map.send_allsky_map_ping', return_value=(True, 'OK')):
                res = client.post('/indi-allsky/ajax/config?camera_id=1', json=valid_payload)
                assert res.status_code == 200
                data = res.get_json()
                assert 'Saved new config' in data['success-message']

        # Mock send_allsky_map_ping warning
        valid_payload['ALLSKYMAP__ENABLE'] = True
        valid_payload['ALLSKYMAP__API_URL'] = 'https://allsky-map.com'
        valid_payload['ALLSKYMAP__API_KEY'] = 'test_api_key'
        valid_payload['RELOAD_ON_SAVE'] = False
        with patch('indi_allsky.flask.views.current_user') as mock_user:
            mock_user.is_admin = True
            mock_user.username = 'admin'
            with patch('indi_allsky.allsky_map.send_allsky_map_ping', return_value=(False, 'Ping failed')):
                res_warn = client.post('/indi-allsky/ajax/config?camera_id=1', json=valid_payload)
                assert res_warn.status_code == 200
                data_warn = res_warn.get_json()
                assert 'Allsky Map Ping Warning' in data_warn['success-message']


def test_ajax_allskymap_request_key_view(flask_app, config_db):
    client = flask_app.test_client()

    # Permission check failure
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': False}):
        res_perm = client.post('/indi-allsky/ajax/allskymap/request_key', json={})
        assert res_perm.status_code == 302

    # Success response
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.allsky_map.request_allsky_map_api_key', return_value=(True, 'test_key_123')):
            res_ok = client.post('/indi-allsky/ajax/allskymap/request_key?camera_id=1', json={'API_URL': 'https://allsky-map.com'})
            assert res_ok.status_code == 200
            assert res_ok.get_json()['api_key'] == 'test_key_123'

        # Failure response
        with patch('indi_allsky.allsky_map.request_allsky_map_api_key', return_value=(False, 'Connection error')):
            res_err = client.post('/indi-allsky/ajax/allskymap/request_key?camera_id=1', json={})
            assert res_err.status_code == 400
            assert res_err.get_json()['error'] == 'Connection error'


def test_ajax_set_time_and_timezone_views(flask_app, config_db):
    client = flask_app.test_client()

    # Set Time permissions & validation
    with patch.dict(flask_app.config, {'LOGIN_DISABLED': False}):
        assert client.post('/indi-allsky/ajax/settime', json={}).status_code == 302
        assert client.post('/indi-allsky/ajax/settimezone', json={}).status_code == 302

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # Invalid payload
        assert client.post('/indi-allsky/ajax/settime?camera_id=1', json={'NEW_DATETIME': 'invalid'}).status_code == 400
        assert client.post('/indi-allsky/ajax/settimezone?camera_id=1', json={'NEW_TIMEZONE': ''}).status_code == 400

        # Success paths with mocked DBus / setTime methods
        with patch('indi_allsky.flask.views.AjaxSetTimeView.setTimeSystemd', return_value=True):
            res_time = client.post('/indi-allsky/ajax/settime?camera_id=1', json={'NEW_DATETIME': '2026-09-18T12:00:00'})
            assert res_time.status_code == 200
            assert res_time.get_json()['success-message'] == 'System time updated.'

        with patch('indi_allsky.flask.views.AjaxSetTimezoneView.setTimezoneSystemd', return_value=True):
            res_tz = client.post('/indi-allsky/ajax/settimezone?camera_id=1', json={'NEW_TIMEZONE': 'UTC'})
            assert res_tz.status_code == 200
            assert res_tz.get_json()['success-message'] == 'System timezone updated.'


def test_config_list_download_restore_views(flask_app, config_db, tmp_path):
    import io
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        with patch('indi_allsky.flask.views.current_user') as mock_user:
            mock_user.is_admin = True
            mock_user.username = 'admin'
            # ConfigListView
            res_list = client.get('/indi-allsky/config/list?camera_id=1')
            assert res_list.status_code == 200

            # ConfigDownloadView (param is 'id', not 'config_id')
            res_down = client.get('/indi-allsky/config/download?id=1')
            assert res_down.status_code == 200

            # ConfigRestoreView GET
            res_rest_get = client.get('/indi-allsky/config/restore?camera_id=1')
            assert res_rest_get.status_code == 200

            # AjaxConfigRestoreView POST
            file_content = json.dumps({
                'INDI_SERVER': 'localhost',
                'CCD_CONFIG': {},
                'INDI_CONFIG_DEFAULTS': {},
                'ENCRYPT_PASSWORDS': False,
            }).encode('utf-8')
            restore_data = {
                'CONFIG_UPLOAD': (io.BytesIO(file_content), 'config.json'),
                'RELOAD_ON_SAVE': 'false',
            }
            res_rest_post = client.post(
                '/indi-allsky/ajax/config/restore?camera_id=1',
                data=restore_data,
                content_type='multipart/form-data'
            )
            assert res_rest_post.status_code == 200


def test_system_info_and_stats_views(flask_app, config_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True, 'INDISERVER_SERVICE_NAME': 'indiserver.service'}):
        with patch('indi_allsky.flask.views.current_user') as mock_user:
            mock_user.is_admin = True
            mock_user.username = 'admin'
            # SystemInfoView
            res_sys = client.get('/indi-allsky/system?camera_id=1')
            assert res_sys.status_code == 200

            # AjaxSystemInfoView (POST method with required form fields)
            with patch('indi_allsky.flask.views.AjaxSystemInfoView.startSystemdUnit', return_value=True):
                res_asys = client.post(
                    '/indi-allsky/ajax/system?camera_id=1',
                    json={'CAMERA_ID': '1', 'SERVICE_HIDDEN': 'indiserver.service', 'COMMAND_HIDDEN': 'start'}
                )
                assert res_asys.status_code == 200

            # AjaxSystemStatsView
            res_stats = client.get('/indi-allsky/ajax/system/stats?camera_id=1')
            assert res_stats.status_code == 200


def test_ajax_indiserver_change_view(flask_app, config_db, tmp_path):
    client = flask_app.test_client()

    # Create dummy service template file in package service dir
    service_dir = Path(__file__).parent.parent.parent / 'service'
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / 'indiserver.service'
    service_file.write_text('%ALLSKY_DIRECTORY%\n%INDI_DRIVER_PATH%\n%INDI_PORT%\n%INDI_CCD_DRIVER%\n%INDI_GPS_DRIVER%\n%INDISERVER_USER%')

    payload = {
        'CAMERA_SERVER_SELECT': '',
        'GPS_SERVER_SELECT': '',
        'RESTART_INDISERVER': True,
    }

    # Dummy indiserver binary path
    indiserver_bin = tmp_path / 'indiserver'
    indiserver_bin.touch()

    user_config_dir = tmp_path / '.config' / 'systemd' / 'user'
    user_config_dir.mkdir(parents=True, exist_ok=True)

    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True, 'INDISERVER_SERVICE_NAME': 'indiserver.service'}):
            with patch('pathlib.Path.exists', side_effect=lambda: True):
                with patch('shutil.which', return_value=str(indiserver_bin)):
                    with patch('os.getlogin', return_value='testuser'):
                        with patch('os.environ.get', return_value=str(tmp_path)):
                            with patch('indi_allsky.flask.views.AjaxIndiServerChangeView.reloadSystemdUnits', return_value=None):
                                with patch('indi_allsky.flask.views.AjaxIndiServerChangeView.restartSystemdUnit', return_value=None):
                                    res = client.post('/indi-allsky/ajax/indiserver', json=payload)
                                    assert res.status_code == 200
                                    assert 'Reconfigure completed' in res.get_json()['success-message']
    finally:
        if service_file.exists():
            service_file.unlink()
