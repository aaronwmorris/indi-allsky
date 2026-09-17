# Legacy Page
This page has not been updated in a while and is no longer maintained.  There are many more settings in the config, but the config is fully managed via the web interface.

# General

All configuration is read from the database.  Almost all of the configuration is managed via the web interface.
You may use the config.py utility to manipulate the configuration from the command line.

| Setting             | Default     | Description |
| ------------------- | ----------- | ----------- |
| CAMERA_INTERFACE    | indi        | (str) Default camera interface |
| INDI_SERVER         | localhost   | (str) Hostname for INDI server |
| INDI_PORT           | 7624        | (int) Port for INDI server |
| INDI_CAMERA_NAME    |             | (str) Camera name (if multiple cameras connected) |
| CCD_CONFIG          |             | (dict) Indi configuration parameters for CCD |
| > NIGHT > GAIN      |             | (int) Gain/ISO for night time |
| > NIGHT > BINNING   |             | (int) Bin mode for night time |
| > MOONMODE > GAIN    |            | (int) Gain/ISO for moon mode|
| > MOONMODE > BINNING |            | (int) Bin mode for moon mode|
| > DAY > GAIN        |             | (int) Gain/ISO for day time |
| > DAY > BINNING     |             | (int) Bin mode for day time |
| INDI_CONFIG_DEFAULTS |            | (dict) Indi default configuration parameters |
| > PROPERTIES        |             | (dict) Indi properties (number) |
| > TEXT              |             | (dict) Indi properties (text) |
| > SWITCHES          |             | (dict) Indi switches |
| CCD_EXPOSURE_MAX    | 15.0        | (float) Maximum exposure time |
| CCD_EXPOSURE_MIN    | Auto detected | (float) Minimum exposure time |
| CCD_EXPOSURE_DEF    | CCD_EXPOSURE_MIN | (float) Default/starting exposure |
| EXPOSURE_PERIOD     | 15.0        | (float) Seconds between beginning of each exposure (Night) |
| EXPOSURE_PERIOD_DAY | 15.0        | (float) Seconds between beginning of each exposure (Day) |
| FOCUS_MODE          | false       | (bool) Focus mode is used to take exposures as quickly as possible to aid in focusing |
| FOCUS_DELAY         | 4.0         | (float) Delay between exposures during focus mode |
| CFA_PATTERN         |             | (str) Override CFA pattern |
| SCNR_ALGORITHM      |             | (str) SCNR (green reduction) algorithm |
| WBR_FACTOR          | 1.0         | (float) Red Balance Adjustment Factor |
| WBG_FACTOR          | 1.0         | (float) Green Balance Adjustment Factor |
| WBB_FACTOR          | 1.0         | (float) Blue Balance Adjustment Factor |
| AUTO_WB             | false       | (bool) Automatic white balance adjustment |
| CCD_COOLING         | false       | (bool) Enable CCD cooling |
| CCD_TEMP            | 15.0        | (float) Target CCD temperature |
| TEMP_DISPLAY        | c           | (str) Temperature display conversion c = celcius, f = fahrenheit, k = kelvin |
| CCD_TEMP_SCRIPT     |             | (str) External script used for CCD temperature.  Used when a camera does not support temperature measurements. |
| GPS_TIMESYNC        | false       | (bool) Sync system time from GPS |
| TARGET_ADU          | varies      | (int) Target image brightness to calculate exposure time |
| TARGET_ADU_DEV      | 10          | (int) Deviation +/- from target ADU to recalculate exposure time (night) |
| TARGET_ADU_DEV_DAY  | 20          | (int) Deviation +/- from target ADU to recalculate exposure time (day) |
| ADU_ROI             | []          | (array) Region of interest to calculate ADU (x1, y1, x2, y2) - Note: ROI calculated using bin 1 coordinates, scaled for bin value |
| DETECT_STARS        | true        | (bool) Enable star detection |
| DETECT_STARS_THOLD  | 0.6         | (float) Star detection threshold |
| DETECT_STARS_METHOD | template    | (str) Star detection method: template or sep |
| DETECT_STARS_SEP_THOLD | 5.0      | (float) SEP detection threshold, in sigma above the local background noise |
| DETECT_STARS_SEP_MAX_RADIUS | 20  | (int) SEP maximum source semi-major axis in pixels, rejects blooming and artifacts |
| DETECT_METEORS      | false       | (bool) Enable meteor detection |
| DETECT_MASK         |             | (str) Image file to use for detection mask |
| DETECT_DRAW         | false       | (bool) Draw detected objects on original image |
| SQM_ROI             | []          | (array) Region of interest for SQM and Star detection |
| LOCATION_LATITUDE   |             | (float) Your latitude for astrometric calculations |
| LOCATION_LONGITUDE  |             | (float) Your longitude for astrometric calculations |
| TIMELAPSE_ENABLE    | true        | (bool) Enable timelapse, keogram, and star trail creation |
| DAYTIME_CAPTURE     | true        | (bool) Perform day time image capture |
| DAYTIME_TIMELAPSE   | true        | (bool) Generate timelapse from day time images |
| DAYTIME_CONTRAST_ENHANCE | false  | (bool) Perform CLAHE contrast enhancement on day time images |
| NIGHT_CONTRAST_ENHANCE   | false  | (bool) Perform CLAHE contrast enhancement on night time images |
| NIGHT_SUN_ALT_DEG   | -6          | (degrees) Altitude of Sun to calculate beginning and end of night |
| NIGHT_MOONMODE_ALT_DEG   | 0      | (degrees) Altitude of Moon to enable night time "moon mode" |
| NIGHT_MOONMODE_PHASE     | 33     | (percent) Minimum illumination of Moon to enable night time "moon mode" |
| WEB_EXTRA_TEXT      |             | (str) File to include in web info box |
| KEOGRAM_ANGLE       | 0           | (float) Angle of image rotation for keogram generation |
| KEOGRAM_H_SCALE     | 100         | (int) Horizontal scaling of keograms |
| KEOGRAM_V_SCALE     | 33          | (int) Vertical scaling of keograms |
| KEOGRAM_LABEL       | true        | (bool) Label keogram timeline |
| STARTRAILS_MAX_ADU  | 50          | (int) Max ADU/brightness of image to be included in star trails |
| STARTRAILS_MASK_THOLD    | 190    | (int) Minimum threshold for star mask generation for star trails |
| STARTRAILS_PIXEL_THOLD   | 1.0    | (float) Cutoff percentage of pixels in mask to eliminate images from star trails |
| STARTRAILS_TIMELAPSE     | True   | (bool) Generate star trails timelapse video |
| STARTRAILS_TIMELAPSE_MINFRAMES | 250  | (int) Minimum number of frames for star trails timelapse |
| IMAGE_FILE_TYPE     | jpg         | (string) Image output type, jpg or png |
| IMAGE_FILE_COMPRESSION   |        | (dict) Default compression values for image types |
| IMAGE_FOLDER        |             | (string) Base folder to save images |
| IMAGE_LABEL         | true        | (bool) Add image timestamps labels |
| IMAGE_LABEL_TEMPLATE     |        | (str) Template for image label |
| IMAGE_EXTRA_TEXT    |             | (string) Filename containing extra text for image |
| IMAGE_DEBAYER       | Auto detected | (string) OpenCV debayering algorithm |
| NIGHT_GRAYSCALE     | false       | Convert image to grayscale at night|
| DAYTIME_GRAYSCALE   | false       | Convert image to grayscale during day |
| IMAGE_ROTATE        |             | (str) Image rotation (cv2 enum) |
| IMAGE_FLIP_V        | true        | (bool) Flip images vertically |
| IMAGE_FLIP_H        | true        | (bool) Flip images horizontally |
| IMAGE_SCALE         | 100         | (percent) Image scaling factor |
| IMAGE_CROP_ROI      | []          | (array) Region of interest to crop image (x1, y1, x2, y2) |
| IMAGE_SAVE_FITS     | false       | (bool) Save raw FITS image data |
| IMAGE_EXPORT_RAW    | ""          | (string) Export raw images this file format |
| IMAGE_EXPORT_FOLDER |             | (string) Folder to export raw tiff files |
| IMAGE_STACK_METHOD  | average     | (string) Method to use for image stacking |
| IMAGE_STACK_COUNT   | 1           | (int) Number of images to stack (1 = disabled) |
| IMAGE_STACK_ALIGN   | false       | (bool) Register/align images |
| IMAGE_ALIGN_DETECTSIGMA | 5       | (int) Alignment sensitivity |
| IMAGE_ALIGN_POINTS  | 50          | (int) Alignment sensitivity |
| IMAGE_ALIGN_SOURCEMINAREA | 10    | (int) Alignment point minimum area |
| IMAGE_STACK_SPLIT   | false       | (bool) Split screen stack |
| IMAGE_EXPIRE_DAYS   | 30          | (days) Number of days to keep original images before deleting |
| TIMELAPSE_EXPIRE_DAYS    | 365    | (days) Number of days to keep timelapse, keogram, and star trails before deleting |
| FFMPEG_FRAMERATE    | 25          | (fps) Target frames per second for timelapse videos |
| FFMPEG_BITRATE      | 2500k       | (kilobytes) Target data rate for timelapse video compression |
| FFMPEG_VFSCALE      | ""          | (str) Scaling option for ffmpeg |
| FFMPEG_CODEC        | libx264     | (str) Codec for encoding timelapse videos |
| TEXT_PROPERTIES     |             | (dict) Default text properties (font, size, etc) |
| > FONT_FACE         |             | (str) OpenCV font name |
| > FONT_HEIGHT       | 30          | (pixels) Font height |
| > FONT_X            | 15          | (pixels) Font X offset |
| > FONT_Y            | 30          | (pixels) Font Y offset |
| > FONT_COLOR        | [200, 200, 200] | (array) R, G, B font color values |
| > FONT_AA           | LINE_AA     | (str) OpenCV antialiasing algorighm |
| > FONT_SCALE        | 0.8         | (float) Font scaling factor |
| > FONT_THICKNESS    | 1           | (int) Font weight |
| > FONT_OUTLINE      | true        | (bool) Enable black outline of text |
| > DATE_FORMAT       | %Y%m%d %H:%M:%S | (str) Date string format |
| ORB_PROPERTIES      |             | (dict) Sun and moon org drawing properties |
| > MODE              | ha          | (str) Orb Mode - ha = Hour Angle, az = Azimuth, alt = Altitude , off = Off|
| > RADIUS            | 9           | (pixels) Radius of orbs |
| > SUN_COLOR         | [255, 255, 255] | (array) R, G, B Color of sun orb |
| > MOON_COLOR        | [128, 128, 128] | (array) R, G, B Color of moon orb |
| FILETRANSFER        |             | (dict) File tranfer configuration |
| > CLASSNAME         |             | (str) File transfer class |
| > HOST              |             | (str) Hostname for file transfer |
| > PORT              | 0           | (int) Port for file transfer (null for protocol default) |
| > USERNAME          |             | (str) Username for file tranfer |
| > PASSWORD          |             | (str) Password for file tranfer |
| > PRIVATE_KEY       |             | (str) Path to a private key file (ssh) |
| > PUBLIC_KEY        |             | (str) Path to a public key file (ssh) |
| > TIMEOUT           | 5.0         | (float) Timeout for file transfer before failing |
| > CERT_BYPASS       | true        | (bool) Bypass certificate validation for file transfers |
| > REMOTE_IMAGE_NAME | latest.{0}  | (str) Python template for remote file name of latest image, extension is automatically selected from IMAGE_FILE_TYPE |
| > LIBCURL_OPTIONS   | {}          | (dict) Additional libcurl options for pycurl based methods |
| > REMOTE_IMAGE_FOLDER        |      | (str) Remote folder to upload latest image |
| > REMOTE_METADATA_NAME       | latest_metadata.json | (str) Filename for remote metadata upload |
| > REMOTE_METADATA_FOLDER     |      | (str) Remote folder to upload metadata |
| > REMOTE_VIDEO_FOLDER        |      | (str) Remote folder to upload time lapse videos |
| > REMOTE_KEOGRAM_FOLDER      |      | (str) Remote folder to upload keograms |
| > REMOTE_STARTRAIL_FOLDER    |      | (str) Remote folder to upload star trails |
| > REMOTE_ENDOFNIGHT_FOLDER   |      | (str) Remote folder to upload Allsky EndOfNight data |
| > UPLOAD_IMAGE        | 0           | (int) Upload latest image every X frames |
| > UPLOAD_METADATA     | false       | (bool) Enable upload of image metadata |
| > UPLOAD_VIDEO        | false       | (bool) Enable timelapse video uploads |
| > UPLOAD_KEOGRAM      | false       | (bool) Enable keogram uploads |
| > UPLOAD_STARTRAIL    | false       | (bool) Enable star trail upload |
| > UPLOAD_ENDOFNIGHT   | false       | (bool) Enable EndOfNight data upload.  This is the data.json file for https://github.com/thomasjacquin/allsky-website |
| MQTTPUBLISH           |             | (dict) MQTT configuration |
| > ENABLE              | false       | (bool) Enable MQTT publishing |
| > TRANSPORT           | tcp         | (str) MQTT Transport - tcp or websockets |
| > HOST                |             | (str) MQTT/Mosquitto server |
| > PORT                | 8883        | (int) MQTT port, 1883 = standard, 8883 = TLS |
| > USERNAME            |             | (str) MQTT user |
| > PASSWORD            |             | (str) MQTT password |
| > BASE_TOPIC          | indi-allsky | (str) Base topic for MQ messages |
| > QOS                 | 0           | (int) MQTT QoS for messages |
| > TLS                 | true        | (bool) Use TLS for MQTT connection |
| > CERT_BYPASS         | true        | (bool) Bypass certificate validation for MQTT connection |
| FITSHEADERS           |             | (array) FITS headers
| LIBCAMERA             |             | (dict) libcamera configuration |
| > IMAGE_FILE_TYPE     | dng         | (str) Image type for libcamera |
| > EXTRA_OPTIONS       |             | (str) Extra options for libcamera-still |