
# Types
CAMERA          = 1
IMAGE           = 2
VIDEO           = 3
KEOGRAM         = 4
STARTRAIL       = 5
STARTRAIL_VIDEO = 6
RAW_IMAGE       = 7
FITS_IMAGE      = 8
USER            = 9
DARK_FRAME      = 10
BPM_FRAME       = 11
METADATA        = 12
PANORAMA_IMAGE  = 13
PANORAMA_VIDEO  = 14
THUMBNAIL       = 15


ENDPOINT_V1 = {
    CAMERA          : 'sync/v1/camera',
    IMAGE           : 'sync/v1/image',
    VIDEO           : 'sync/v1/video',
    KEOGRAM         : 'sync/v1/keogram',
    STARTRAIL       : 'sync/v1/startrail',
    STARTRAIL_VIDEO : 'sync/v1/startrailvideo',
    RAW_IMAGE       : 'sync/v1/rawimage',
    FITS_IMAGE      : 'sync/v1/fitsimage',
    PANORAMA_IMAGE  : 'sync/v1/panoramaimage',
    PANORAMA_VIDEO  : 'sync/v1/panoramavideo',
    THUMBNAIL       : 'sync/v1/thumbnail',
}


# File transfers
TRANSFER_UPLOAD  = 501
TRANSFER_MQTT    = 502
TRANSFER_S3      = 503
TRANSFER_SYNC_V1 = 504
TRANSFER_YOUTUBE = 505
DELETE_S3        = 506


# Status
STATUS_STARTING     = 701
STATUS_RUNNING      = 702
STATUS_SLEEPING     = 703
STATUS_RELOADING    = 704
STATUS_STOPPING     = 705
STATUS_STOPPED      = 706
STATUS_NOCAMERA     = 707
STATUS_NOINDISERVER = 708


# CFA Types
CFA_RGGB = 46  # cv2.COLOR_BAYER_BG2BGR
CFA_GRBG = 47  # cv2.COLOR_BAYER_GB2BGR
CFA_BGGR = 48  # cv2.COLOR_BAYER_RG2BGR
CFA_GBRG = 49  # cv2.COLOR_BAYER_GR2BGR

CFA_STR_MAP = {
    'RGGB' : CFA_RGGB,
    'GRBG' : CFA_GRBG,
    'BGGR' : CFA_BGGR,
    'GBRG' : CFA_GBRG,
    None   : None,
    ''     : None,  # sv305 edge case
}

CFA_MAP_STR = {
    CFA_RGGB : 'RGGB',
    CFA_GRBG : 'GRBG',
    CFA_BGGR : 'BGGR',
    CFA_GBRG : 'GBRG',
    None     : 'None',
}


# Leaving gaps for addtional classifications
SMOKE_RATING_NODATA  = -1
SMOKE_RATING_CLEAR   = 1
SMOKE_RATING_LIGHT   = 30
SMOKE_RATING_MEDIUM  = 60
SMOKE_RATING_HEAVY   = 90

SMOKE_RATING_MAP_STR = {
    SMOKE_RATING_CLEAR   : 'Clear',
    SMOKE_RATING_LIGHT   : 'Light',
    SMOKE_RATING_MEDIUM  : 'Medium',
    SMOKE_RATING_HEAVY   : 'Heavy',
    SMOKE_RATING_NODATA  : 'No Data',
    None       : 'No Data',  # legacy
    0          : 'No Data',  # legacy
    'Clear'    : 'Clear',    # legacy
    'Light'    : 'Light',    # legacy
    'Medium'   : 'Medium',   # legacy
    'Heavy'    : 'Heavy',    # legacy
    'No Data'  : 'No Data',  # legacy
}


# Satellites
SATELLITE_VISUAL    = 800
SATELLITE_STARLINK  = 801
SATELLITE_STATIONS  = 802



# Sensor types
SENSOR_TEMPERATURE          = 600
SENSOR_RELATIVE_HUMIDITY    = 601
SENSOR_ATMOSPHERIC_PRESSURE = 602
SENSOR_WIND_SPEED           = 603
SENSOR_PRECIPITATION        = 604
SENSOR_CONCENTRATION        = 605
SENSOR_LIGHT_LUX            = 606
SENSOR_LIGHT_SQM            = 607
SENSOR_LIGHT_MISC           = 608
SENSOR_FAN_SPEED            = 609
SENSOR_PERCENTAGE           = 610
SENSOR_DIRECTION_AZIMUTH    = 612
SENSOR_STATE                = 613
SENSOR_MISC                 = 620

