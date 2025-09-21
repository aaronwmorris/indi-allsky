
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
MINI_VIDEO      = 16
DB_BACKUP       = 17


ENDPOINT_V1 = {
    CAMERA          : 'sync/v1/camera',
    IMAGE           : 'sync/v1/image',
    VIDEO           : 'sync/v1/video',
    MINI_VIDEO      : 'sync/v1/minivideo',
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
STATUS_PAUSED       = 709
STATUS_CAMERAERROR  = 710


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


# Position indexes
POSITION_LATITUDE   = 0
POSITION_LONGITUDE  = 1
POSITION_ELEVATION  = 2


# Exposure indexes
EXPOSURE_CURRENT    = 0
EXPOSURE_MIN_NIGHT  = 1
EXPOSURE_MIN_DAY    = 2
EXPOSURE_MAX        = 3


# Gain indexes
GAIN_CURRENT        = 0
GAIN_NEXT           = 1
GAIN_MIN            = 2
GAIN_MAX_NIGHT      = 3
GAIN_MAX_MOONMODE   = 4


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


SENSOR_INDEX_MAP = {
    'sensor_user_0'     : 0,
    'sensor_user_1'     : 1,
    'sensor_user_2'     : 2,
    'sensor_user_3'     : 3,
    'sensor_user_4'     : 4,
    'sensor_user_5'     : 5,
    'sensor_user_6'     : 6,
    'sensor_user_7'     : 7,
    'sensor_user_8'     : 8,
    'sensor_user_9'     : 9 ,
    'sensor_user_10'    : 10,
    'sensor_user_11'    : 11,
    'sensor_user_12'    : 12,
    'sensor_user_13'    : 13,
    'sensor_user_14'    : 14,
    'sensor_user_15'    : 15,
    'sensor_user_16'    : 16,
    'sensor_user_17'    : 17,
    'sensor_user_18'    : 18,
    'sensor_user_19'    : 19,
    'sensor_user_20'    : 20,
    'sensor_user_21'    : 21,
    'sensor_user_22'    : 22,
    'sensor_user_23'    : 23,
    'sensor_user_24'    : 24,
    'sensor_user_25'    : 25,
    'sensor_user_26'    : 26,
    'sensor_user_27'    : 27,
    'sensor_user_28'    : 28,
    'sensor_user_29'    : 29,
    'sensor_user_30'    : 30,
    'sensor_user_31'    : 31,
    'sensor_user_32'    : 32,
    'sensor_user_33'    : 33,
    'sensor_user_34'    : 34,
    'sensor_user_35'    : 35,
    'sensor_user_36'    : 36,
    'sensor_user_37'    : 37,
    'sensor_user_38'    : 38,
    'sensor_user_39'    : 39,
    'sensor_user_40'    : 40,
    'sensor_user_41'    : 41,
    'sensor_user_42'    : 42,
    'sensor_user_43'    : 43,
    'sensor_user_44'    : 44,
    'sensor_user_45'    : 45,
    'sensor_user_46'    : 46,
    'sensor_user_47'    : 47,
    'sensor_user_48'    : 48,
    'sensor_user_49'    : 49,
    'sensor_user_50'    : 50,
    'sensor_user_51'    : 51,
    'sensor_user_52'    : 52,
    'sensor_user_53'    : 53,
    'sensor_user_54'    : 54,
    'sensor_user_55'    : 55,
    'sensor_user_56'    : 56,
    'sensor_user_57'    : 57,
    'sensor_user_58'    : 58,
    'sensor_user_59'    : 59,

    'sensor_temp_0'     : 0,
    'sensor_temp_1'     : 1,
    'sensor_temp_2'     : 2,
    'sensor_temp_3'     : 3,
    'sensor_temp_4'     : 4,
    'sensor_temp_5'     : 5,
    'sensor_temp_6'     : 6,
    'sensor_temp_7'     : 7,
    'sensor_temp_8'     : 8,
    'sensor_temp_9'     : 9,
    'sensor_temp_10'    : 10,
    'sensor_temp_11'    : 11,
    'sensor_temp_12'    : 12,
    'sensor_temp_13'    : 13,
    'sensor_temp_14'    : 14,
    'sensor_temp_15'    : 15,
    'sensor_temp_16'    : 16,
    'sensor_temp_17'    : 17,
    'sensor_temp_18'    : 18,
    'sensor_temp_19'    : 19,
    'sensor_temp_20'    : 20,
    'sensor_temp_21'    : 21,
    'sensor_temp_22'    : 22,
    'sensor_temp_23'    : 23,
    'sensor_temp_24'    : 24,
    'sensor_temp_25'    : 25,
    'sensor_temp_26'    : 26,
    'sensor_temp_27'    : 27,
    'sensor_temp_28'    : 28,
    'sensor_temp_29'    : 29,
    'sensor_temp_30'    : 30,
    'sensor_temp_31'    : 31,
    'sensor_temp_32'    : 32,
    'sensor_temp_33'    : 33,
    'sensor_temp_34'    : 34,
    'sensor_temp_35'    : 35,
    'sensor_temp_36'    : 36,
    'sensor_temp_37'    : 37,
    'sensor_temp_38'    : 38,
    'sensor_temp_39'    : 39,
    'sensor_temp_40'    : 40,
    'sensor_temp_41'    : 41,
    'sensor_temp_42'    : 42,
    'sensor_temp_43'    : 43,
    'sensor_temp_44'    : 44,
    'sensor_temp_45'    : 45,
    'sensor_temp_46'    : 46,
    'sensor_temp_47'    : 47,
    'sensor_temp_48'    : 48,
    'sensor_temp_49'    : 49,
    'sensor_temp_50'    : 50,
    'sensor_temp_51'    : 51,
    'sensor_temp_52'    : 52,
    'sensor_temp_53'    : 53,
    'sensor_temp_54'    : 54,
    'sensor_temp_55'    : 55,
    'sensor_temp_56'    : 56,
    'sensor_temp_57'    : 57,
    'sensor_temp_58'    : 58,
    'sensor_temp_59'    : 59,

    # legacy
    0                   : 0,
    1                   : 1,
    2                   : 2,
    3                   : 3,
    4                   : 4,
    5                   : 5,
    6                   : 6,
    7                   : 7,
    8                   : 8,
    9                   : 9,
    10                  : 10,
    11                  : 11,
    12                  : 12,
    13                  : 13,
    14                  : 14,
    15                  : 15,
    16                  : 16,
    17                  : 17,
    18                  : 18,
    19                  : 19,
    20                  : 20,
    21                  : 21,
    22                  : 22,
    23                  : 23,
    24                  : 24,
    25                  : 25,
    26                  : 26,
    27                  : 27,
    28                  : 28,
    29                  : 29,
    100                 : 0,
    101                 : 1,
    102                 : 2,
    103                 : 3,
    104                 : 4,
    105                 : 5,
    106                 : 6,
    107                 : 7,
    108                 : 8,
    109                 : 9,
    110                 : 10,
    111                 : 11,
    112                 : 12,
    113                 : 13,
    114                 : 14,
    115                 : 15,
    116                 : 16,
    117                 : 17,
    118                 : 18,
    119                 : 19,
    120                 : 20,
    121                 : 21,
    122                 : 22,
    123                 : 23,
    124                 : 24,
    125                 : 25,
    126                 : 26,
    127                 : 27,
    128                 : 28,
    129                 : 29,
    '0'                 : 0,
    '1'                 : 1,
    '2'                 : 2,
    '3'                 : 3,
    '4'                 : 4,
    '5'                 : 5,
    '6'                 : 6,
    '7'                 : 7,
    '8'                 : 8,
    '9'                 : 9,
    '10'                : 10,
    '11'                : 11,
    '12'                : 12,
    '13'                : 13,
    '14'                : 14,
    '15'                : 15,
    '16'                : 16,
    '17'                : 17,
    '18'                : 18,
    '19'                : 19,
    '20'                : 20,
    '21'                : 21,
    '22'                : 22,
    '23'                : 23,
    '24'                : 24,
    '25'                : 25,
    '26'                : 26,
    '27'                : 27,
    '28'                : 28,
    '29'                : 29,
}


INDISERVER_CAMERA_MAP = {
    'indi_simulator_ccd'    : 'CCD Simulator',
    'indi_asi_ccd'          : 'ZWO ASI',
    'indi_asi_single_ccd'   : 'ZWO ASI (Single)',
    'indi_playerone_ccd'    : 'PlayerOne Astronomy',
    'indi_playerone_single_ccd' : 'PlayerOne Astronomy (Single)',
    'indi_toupcam_ccd'      : 'ToupTek',
    'indi_altair_ccd'       : 'Altair',
    'indi_omegonprocam_ccd' : 'Omegon',
    'indi_ogmacam_ccd'      : 'Ogma',
    'indi_tscam_ccd'        : 'indi_tscam_ccd',
    'indi_nncam_ccd'        : 'indi_nncam_ccd',
    'indi_svbony_ccd'       : 'SVBony',
    #'indi_svbonycam_ccd'    : 'SVBony',
    'indi_qhy_ccd'          : 'QHY',
    'indi_sx_ccd'           : 'Starlight Xpress',
    'indi_dsi_ccd'          : 'Meade DSI',
    'indi_libcamera_ccd'    : 'libcamera (BETA)',
    'indi_gphoto_ccd'       : 'DSLR gphoto',
    'indi_canon_ccd'        : 'Canon DSLR',
    'indi_sony_ccd'         : 'Sony DSLR',
    'indi_nikon_ccd'        : 'Nikon DSLR',
    'indi_fuji_ccd'         : 'Fuji DSLR',
    'indi_pentax_ccd'       : 'Pentax DSLR',
    'indi_v4l2_ccd'         : 'Linux V4L2',
    'indi_webcam_ccd'       : 'Web Camera',
}


INDISERVER_GPS_MAP = {
    'indi_gpsd'             : 'GPSd',
    'indi_gpsnmea'          : 'GPSd NEMA',
    'indi_simulator_gps'    : 'GPS Simulator',
}

